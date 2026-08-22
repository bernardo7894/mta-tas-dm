--[[
		* TAS - Recording Tool by chris1384 @2020
		* version 1.4.5
]]

local tas = {
	var = {
		cooldowns = {},
		handles = {},
		warps = {},
		isCreatingDummy = false,
		automation = nil,
	},
	settings = {
	
		-- // Saving and loading records
		
		enableGlobalAccess = true, -- enable global access for files to be saved and loaded by players (useful for sharing between players)
		saveACLRequirement = {"Console", "Admin", "SuperModerator"}, -- the ACL Group requirements for a player to save TAS files serverside.
		--saveACLOverwriteRequirement = {"Console", "Admin"}, -- [UNUSED] the ACL Group requirements for a player to overwrite previously saved TAS file serverside.
		loadACLRequirement = {"Everyone"}, -- same as saving (must be logged in)
		
		globalAnnouncements = true, -- enable server announcements whenever a player is saving/loading a file
		
		saveWarpData = true, -- save warp data to TAS files
		allowSaveOverride = true, -- if a TAS file exists already on the server, override it instead of returning an error
		-- //
	},
}

-- // Registered server commands
tas.registered_commands = {	
	load_record_global = "loadrg",
	save_record_global = "saverg",
	force_cancel = "forcecancel",
}

-- // Reference-capture automation
--
-- The TAS client owns the local .tas file and telemetry capture.  The server
-- side only orchestrates map selection and tells the target client when the
-- race vehicle exists.  This keeps the existing client-private save layout
-- intact while making the repetitive reference-recording workflow callable
-- from MTA's authenticated HTTP export interface.
tas.automation = {
	nextId = 0,
	timeout = 120000,
	captureTimeout = 900000,
	pollInterval = 250,
}

function tas.automation_is_terminal(state)
	return state == "completed" or state == "failed" or state == "cancelled"
end

function tas.automation_stop_timer()
	if tas.var.automationTimer and isTimer(tas.var.automationTimer) then
		killTimer(tas.var.automationTimer)
	end
	tas.var.automationTimer = nil
end

function tas.automation_fail(message)
	local active = tas.var.automation
	if not active or tas.automation_is_terminal(active.state) then return false end

	active.state = "failed"
	active.message = tostring(message or "Unknown automation failure")
	active.error = active.message
	active.finishedAt = getTickCount()
	tas.automation_stop_timer()

	if active.clientStarted and active.player and isElement(active.player) then
		triggerClientEvent(active.player, "tas:automationAbort", resourceRoot, active.id, active.message)
	end

	outputServerLog("[SERVER-TAS] reference capture #"..tostring(active.id).." failed: "..active.message)
	return false
end

function tas.automation_resolve_map(mapName)
	if not getResourceFromName("mapmanager") or getResourceState(getResourceFromName("mapmanager")) ~= "running" then
		return nil, "mapmanager is not running"
	end

	local direct = getResourceFromName(mapName)
	if direct and exports.mapmanager:isMap(direct) then
		return direct
	end

	local wanted = string.lower(mapName)
	local normalizedWanted = string.gsub(wanted, "[^%w]", "")
	for _, map in ipairs(exports.mapmanager:getMaps()) do
		local friendlyName = getResourceInfo(map, "name")
		if friendlyName then
			local lowerFriendlyName = string.lower(friendlyName)
			if lowerFriendlyName == wanted or string.gsub(lowerFriendlyName, "[^%w]", "") == normalizedWanted then
				return map
			end
		end
	end

	return nil, "map not found: "..mapName
end

function tas.automation_resolve_player(targetName)
	local players = getElementsByType("player")
	if #players == 0 then return nil, "no player is connected" end

	if type(targetName) == "string" and targetName ~= "" then
		local wanted = string.lower(targetName)
		local exact, partial = nil, nil
		for _, player in ipairs(players) do
			local playerName = getPlayerName(player)
			local lowerName = string.lower(playerName)
			if lowerName == wanted then
				exact = player
			elseif string.find(lowerName, wanted, 1, true) then
				if partial then return nil, "target player name is ambiguous" end
				partial = player
			end
		end
		if exact then return exact end
		if partial then return partial end
		return nil, "target player not found: "..targetName
	end

	-- HTTP callers are normally the same account as the local player.  Prefer
	-- that match, then accept the only connected player.  Refuse to guess when
	-- this is a multi-player server.
	if user then
		local accountName = getAccountName(user)
		if accountName then
			for _, player in ipairs(players) do
				local account = getPlayerAccount(player)
				if account and not isGuestAccount(account) and getAccountName(account) == accountName then
					return player
				end
			end
		end
	end

	if #players == 1 then return players[1] end
	return nil, "targetPlayer is required when multiple players are connected"
end

function tas.automation_tick()
	local active = tas.var.automation
	if not active then
		tas.automation_stop_timer()
		return
	end
	if tas.automation_is_terminal(active.state) then
		tas.automation_stop_timer()
		return
	end

	local timeout = active.state == "capturing" and tas.automation.captureTimeout or tas.automation.timeout
	if getTickCount() - active.startedAt > timeout then
		local message = active.state == "capturing"
			and "timed out waiting for playback capture to finish"
			or "timed out waiting for the map or race vehicle"
		tas.automation_fail(message)
		return
	end

	if not active.player or not isElement(active.player) then
		tas.automation_fail("target player disconnected")
		return
	end

	if active.clientStarted then return end

	local runningMap = exports.mapmanager:getRunningGamemodeMap()
	if runningMap ~= active.mapResource then
		active.state = "changing_map"
		active.message = "Waiting for map: "..active.mapName
		return
	end

	active.state = "waiting_for_vehicle"
	active.message = "Waiting for the race vehicle"
	local vehicle = getPedOccupiedVehicle(active.player)
	if not vehicle or not isElement(vehicle) then return end

	active.vehicle = vehicle
	active.clientStarted = true
	active.state = "loading_record"
	active.message = "Loading the client-side TAS recording"
	triggerClientEvent(active.player, "tas:automationStart", resourceRoot, active.id, active.recordName, active.outputName)
end

function tas.startReferenceCapture(mapName, recordName, outputName, targetName)
	if tas.var.automation and not tas.automation_is_terminal(tas.var.automation.state) then
		return false, "another reference capture is already running"
	end

	if type(mapName) ~= "string" or mapName == "" or #mapName > 256 then
		return false, "mapName is required"
	end
	if type(recordName) ~= "string" or recordName == "" or #recordName > 128 then
		return false, "recordName is required"
	end
	if type(outputName) ~= "string" or outputName == "" or #outputName > 128 then
		return false, "outputName is required"
	end
	if string.find(recordName, "[/\\]") or string.find(recordName, "%.%.") then
		return false, "recordName contains an invalid path"
	end
	if string.find(outputName, "[/\\]") or string.find(outputName, "%.%.") then
		return false, "outputName contains an invalid path"
	end

	local mapResource, mapError = tas.automation_resolve_map(mapName)
	if not mapResource then return false, mapError end
	if not getResourceFromName("race") then return false, "race gamemode is not installed" end

	local player, playerError = tas.automation_resolve_player(targetName)
	if not player then return false, playerError end

	tas.automation.nextId = tas.automation.nextId + 1
	local active = {
		id = tas.automation.nextId,
		state = "changing_map",
		message = "Changing to map: "..mapName,
		mapName = mapName,
		mapResource = mapResource,
		recordName = recordName,
		outputName = outputName,
		player = player,
		startedAt = getTickCount(),
	}
	tas.var.automation = active

	-- Pass the resource name to mapmanager after resolving the friendly name.
	-- This also accepts convenient spellings such as "DM Skynet v5 Etnies II"
	-- for a map whose displayed name contains [DM] and a hyphen.
	local changed = exports.mapmanager:changeGamemodeByName("race", getResourceName(mapResource), true)
	if changed == false then
		tas.automation_fail("mapmanager rejected map: "..mapName)
		return false, tas.var.automation.message
	end

	tas.var.automationTimer = setTimer(tas.automation_tick, tas.automation.pollInterval, 0)
	outputServerLog("[SERVER-TAS] started reference capture #"..tostring(active.id).." for "..getPlayerName(player).." on "..mapName)
	return true, active.id, active.message
end

function tas.automation_status()
	local active = tas.var.automation
	if not active then return {ok = true, state = "idle"} end

	return {
		ok = true,
		id = active.id,
		state = active.state,
		message = active.message,
		error = active.error,
		map = active.mapName,
		record = active.recordName,
		output = active.outputName,
		player = active.player and isElement(active.player) and getPlayerName(active.player) or nil,
		startedAt = active.startedAt,
		finishedAt = active.finishedAt,
	}
end

function tas.automation_http_authorized()
	if not user then return false, "HTTP authentication is required" end
	local accountName = getAccountName(user)
	if not accountName or not hasObjectPermissionTo("user."..accountName, "general.http", false) then
		return false, "HTTP account lacks general.http permission"
	end
	return true
end

-- HTTP exports are deliberately authenticated by MTA and additionally require
-- the account's normal general.http ACL right.  They are the interface used by
-- the local Python helper, not a public client event.
function startReferenceCapture(mapName, recordName, outputName, targetName)
	local allowed, reason = tas.automation_http_authorized()
	if not allowed then return {ok = false, state = "failed", error = reason} end

	local ok, idOrError, message = tas.startReferenceCapture(mapName, recordName, outputName, targetName)
	if not ok then
		return {ok = false, state = "failed", error = tostring(idOrError)}
	end
	return {ok = true, id = idOrError, state = "changing_map", message = message}
end

function getReferenceCaptureStatus()
	local allowed, reason = tas.automation_http_authorized()
	if not allowed then return {ok = false, state = "failed", error = reason} end
	return tas.automation_status()
end

addEvent("tas:automationStatus", true)
addEventHandler("tas:automationStatus", root, function(id, state, message)
	local active = tas.var.automation
	if not active or client ~= active.player or id ~= active.id then return end
	if type(state) ~= "string" or tas.automation_is_terminal(active.state) then return end

	active.state = state
	active.message = tostring(message or "")
	if state == "failed" or state == "cancelled" then active.error = active.message end
	active.updatedAt = getTickCount()
	if tas.automation_is_terminal(state) then
		active.finishedAt = getTickCount()
		tas.automation_stop_timer()
		outputServerLog("[SERVER-TAS] reference capture #"..tostring(active.id).." "..state..": "..active.message)
	end
end)

-- A playback failure can mean that the player left an otherwise live vehicle,
-- rather than that the vehicle element was destroyed. The client sends this
-- one-shot scalar snapshot before reporting automation cancellation. Validate
-- both event source and client so this remains diagnostic, not a public log
-- injection surface.
addEvent("tas:playbackFailureDiagnostic", true)
addEventHandler("tas:playbackFailureDiagnostic", root, function(context)
	local active = tas.var.automation
	if client ~= source or not active or active.player ~= client or type(context) ~= "table" then return end
	local encoded = toJSON(context, true) or "{}"
	outputServerLog("[SERVER-TAS] playback failure #"..tostring(active.id).." diagnostic: "..encoded)
end)

-- // Initialization
function tas.init()

	for _,v in pairs(tas.registered_commands) do
		addCommandHandler(v, tas.commands)
	end
	
	for _,v in ipairs(getElementsByType("player")) do
		tas.var.warps[v] = {}
		removeElementData(v, "tas:clientWarps")
	end
end
addEventHandler("onResourceStart", resourceRoot, tas.init)

function tas.commands(player, cmd, ...)

	local args = {...}
	
	local r, g, b = getPlayerNametagColor(player)
	local full_name = string.format("#%.2X%.2X%.2X", r, g, b) .. getPlayerName(player)

	if cmd == tas.registered_commands.save_record_global then
	
		if tas.settings.enableGlobalAccess ~= true then tas.prompt("This command has been disabled!", player, 255, 100, 100) return end
		
		if tas.var.cooldowns[player] ~= nil then tas.prompt("Please wait for your record to be $$saved##/$$loaded##!", player, 255, 100, 100) return end
		
		if args[1] == nil then 
			tas.prompt("Server saving failed, please specify a $$name ##for your file!", player, 255, 100, 100) 
			tas.prompt("Example: $$/"..tas.registered_commands.save_record_global.." od3", player, 255, 100, 100) 
			return 
		end
		
		local permissionCheck = false
		
		local account = getPlayerAccount(player)
		if (account and not isGuestAccount(account)) then
			for index,aclGroup in ipairs(tas.settings.saveACLRequirement) do
				if isObjectInACLGroup("user."..getAccountName(account), aclGetGroup(aclGroup)) then
					permissionCheck = true
					break
				end
			end
		end
		
		if not permissionCheck then tas.prompt("You don't have access to use this command!", player, 255, 100, 100) return end
		
		local fileTarget = "saves/"..args[1]..".tas"
		if fileExists(fileTarget) then 
			if not tas.settings.allowSaveOverride then
				tas.prompt("Server saving failed, file with the same name $$already ##exists!", player, 255, 100, 100) 
				return 
			end
		end
		
		tas.prompt("Requesting client for data..", player, 100, 255, 100)
		setTimer(triggerClientEvent, 500, 1, player, "tas:onClientGlobalRequest", player, "save", tostring(args[1]))
		tas.var.cooldowns[player] = true
		
	elseif cmd == tas.registered_commands.load_record_global then
	
		if tas.settings.enableGlobalAccess ~= true then tas.prompt("This command has been disabled!", player, 255, 100, 100) return end
		
		if tas.var.cooldowns[player] ~= nil then tas.prompt("Please wait for your record to be saved/loaded!", player, 255, 100, 100) return end
		
		if args[1] == nil then 
			tas.prompt("Server loading failed, please specify a $$name ##for your file!", player, 255, 100, 100) 
			tas.prompt("Example: $$/"..tas.registered_commands.load_record_global.." ar2", player, 255, 100, 100) 
			return 
		end
		
		local permissionCheck = false
		
		local account = getPlayerAccount(player)
		if (account and not isGuestAccount(account)) then
			for index,aclGroup in ipairs(tas.settings.loadACLRequirement) do
				if isObjectInACLGroup("user."..getAccountName(account), aclGetGroup(aclGroup)) then
					permissionCheck = true
					break
				end
			end
		end
		
		if not permissionCheck then tas.prompt("You don't have access to use this command!", player, 255, 100, 100) return end
		
		local fileTarget = "saves/"..args[1]..".tas"
		if not fileExists(fileTarget) then tas.prompt("Server loading failed, file does $$not ##exist!", player, 255, 100, 100) return end
		
		local load_file = fileOpen(fileTarget)
		
		if load_file then
			local load_size = fileGetSize(load_file)
			local load_data = fileRead(load_file, load_size)
			
			local handleLoad = triggerLatentClientEvent(player, "tas:onClientGlobalRequest", 10^6, false, player, "load", load_data, args[1])
			
			if handleLoad then
				local handles = getLatentEventHandles(player)
				tas.var.handles[player] = handles[#handles]
			end
			
			if tas.settings.globalAnnouncements then
				tas.prompt(full_name.." ##has requested file '$$"..args[1]..".tas##'! Sending file..", root, 255, 255, 100)
			else
				tas.prompt("Requested file '$$"..args[1]..".tas##' for downloading! Sending file..", player, 255, 255, 100)
			end
			
			fileClose(load_file)
			
			tas.var.cooldowns[player] = true
		else
			tas.prompt("Error loading the file. (not exising/reading file not permitted)", player, 255, 255, 100)
		end
	
	elseif cmd == tas.registered_commands.force_cancel then
	
		if tas.var.handles[player] then
			cancelLatentEvent(tas.var.handles[player])
		end
		
		tas.var.cooldowns[player] = nil
		triggerClientEvent(player, "tas:onClientGlobalRequest", player, "forcecancel")
		
	end
end

addEvent("tas:onGlobalRequest", true)
addEventHandler("tas:onGlobalRequest", root, function(handleType, ...)

	local global_data = {...}
	
	local player = source
	local r, g, b = getPlayerNametagColor(player)
	local full_name = string.format("#%.2X%.2X%.2X", r, g, b) .. getPlayerName(player)
	
	-- // Saving
	if handleType == "save" then

		local tas_data = global_data[1]
		local tas_warps = global_data[2]
		local tas_fileName = global_data[3]
		
		if #tas_data > 0 then
	
			local fileTarget = "saves/"..tas_fileName..".tas"

			if fileExists(fileTarget) then 
				if tas.settings.allowSaveOverride then
					tas.prompt("Warning! Existing server file $$("..fileTarget..") ##has been overwritten!", root, 255, 150, 100)
					fileDelete(fileTarget) -- no more annoyance
				else
					tas.prompt("Server saving failed, file with the same name $$already ##exists!", player, 255, 100, 100) -- might happen
					return 
				end
			end
				
			local save_file = fileCreate(fileTarget)
			if save_file then
			
				-- // Header
				fileWrite(save_file, "# "..tas_fileName..".tas file created on "..os.date().."\n")
				fileWrite(save_file, "# Author: "..string.gsub(full_name, "#%x%x%x%x%x%x", "").." | Frames: "..tostring(#tas_data).." | Warps: "..tostring(#tas_warps).."\n\n")
				-- //
				
				-- // Recording part
				fileWrite(save_file, "+run\n")
				
				for i=1, #tas_data do
				
					local run = tas_data[i]
					local nos = "-1"
					
					if run.n then
						local active = ((run.n.a == true) and "1") or "0"
						nos = tostring(run.n.c)..","..tostring(tas.float(run.n.l))..",".. active
					end
					
					local keys = ""
					if run.k then
						keys = table.concat(run.k, ",")
					end
					
					fileWrite(save_file, string.format("%s|%s,%s,%s|%s,%s,%s|%s,%s,%s|%s,%s,%s|%d|%d|%s|%s", tas.float(run.tick), tas.float(run.p[1]), tas.float(run.p[2]), tas.float(run.p[3]), tas.float(run.r[1]), tas.float(run.r[2]), tas.float(run.r[3]), tas.float(run.v[1]), tas.float(run.v[2]), tas.float(run.v[3]), tas.float(run.rv[1]), tas.float(run.rv[2]), tas.float(run.rv[3]), math.max(run.h), run.m, nos, keys).."\n")
				end
				
				fileWrite(save_file, "-run\n")
				-- //
				
				-- // Warps part
				if #tas_warps > 0 and tas.settings.saveWarpData then
					fileWrite(save_file, "+warps\n")
					for i=1, #tas_warps do
					
						local warp = tas_warps[i]
						local nos = "-1"
						
						if warp.n then
							local active = ((warp.n.a == true) and "1") or "0"
							nos = tostring(warp.n.c)..","..tostring(tas.float(warp.n.l))..",".. active
						end
						
						if warp.tick then
							fileWrite(save_file, string.format("%d|%s|%s,%s,%s|%s,%s,%s|%s,%s,%s|%s,%s,%s|%d|%d|%s", warp.frame, tas.float(warp.tick), tas.float(warp.p[1]), tas.float(warp.p[2]), tas.float(warp.p[3]), tas.float(warp.r[1]), tas.float(warp.r[2]), tas.float(warp.r[3]), tas.float(warp.v[1]), tas.float(warp.v[2]), tas.float(warp.v[3]), tas.float(warp.rv[1]), tas.float(warp.rv[2]), tas.float(warp.rv[3]), warp.h, warp.m, nos).."\n")
						end
						
					end
					fileWrite(save_file, "-warps")
				end
				-- //
				
				fileClose(save_file)
			
			end
			
			if tas.settings.globalAnnouncements then
				tas.prompt(full_name.." ##has saved $$'saves/"..tas_fileName..".tas' ##to the server!", root, 255, 255, 100)
			else
				tas.prompt("$$'saves/"..tas_fileName..".tas' ##has been sent to the server successfully!", player, 255, 255, 100)
			end
			
		else
			tas.prompt("Server saving error, no $$data ##found!", player, 255, 100, 100)
		end
		
		tas.var.cooldowns[player] = nil
	
	elseif handleType == "success_load" then
		tas.var.handles[player] = nil
		tas.var.cooldowns[player] = nil
	
	elseif handleType == "failed_save" then
		tas.var.cooldowns[player] = nil
		
	end
	-- //
end)


-- // Use the event given by the Race Default
addEvent("onRaceStateChanging")
addEventHandler("onRaceStateChanging", root, function(new)

	local everyone = getElementsByType("player")
	
	if new == "Running" then
		triggerClientEvent(everyone, "tas:triggerCommand", resourceRoot, "Started")
		
	elseif new == "NoMap" or new == "PostFinish" then
		triggerClientEvent(everyone, "tas:triggerCommand", resourceRoot, "Stop")
		
	end
	
end)

-- // Model Change Resync with clients (might break up) | NOS syncing
addEvent("tas:syncClient", true)
addEventHandler("tas:syncClient", root, function(event, value)

	local vehicle = source
	
	if event == "vehiclechange" then
		setElementModel(vehicle, value)
		
	elseif event == "nos" then
		if value == true then
			addVehicleUpgrade(vehicle, 1010)
		else
			removeVehicleUpgrade(vehicle, getVehicleUpgradeOnSlot(vehicle, 8))
		end
		
	end
end)

addEvent("tas:syncWarps", true)
addEventHandler("tas:syncWarps", root, function(action, data)
	if client then
	
		if not tas.var.warps[client] then tas.var.warps[client] = {} end
		
		if action == "import" then
			tas.var.warps[client] = data
			setElementData(client, "tas:clientWarps", tas.var.warps[client])
			
		elseif action == "save" then
			table.insert(tas.var.warps[client], data)
			setElementData(client, "tas:clientWarps", tas.var.warps[client])
			
		elseif action == "delete" then
			table.remove(tas.var.warps[client], data)
			setElementData(client, "tas:clientWarps", tas.var.warps[client])
			
		elseif action == "clear" then
			tas.var.warps[client] = {}
			removeElementData(client, "tas:clientWarps")
			
		end
	end
end)


-- // Semi-wrapper for edf vehicle creator
addEvent("tas:edfCreate", true)
addEventHandler("tas:edfCreate", root, function()
	tas.var.isCreatingDummy = true
end)

-- // Event triggered by editor
addEvent("onElementCreate")
addEventHandler("onElementCreate", root, function()
	local element = source
	if getElementType(element) == "vehicle" then
		if tas.var.isCreatingDummy then -- yeah we sure are applying these down here
		
			-- // Apply position and rotation
			local x, y, z = getElementPosition(source)
			exports.edf:edfSetElementPosition(source, x, y, z)
			local rx, ry, rz = getElementRotation(source)
			exports.edf:edfSetElementRotation(source, rx, ry, rz, "ZYX")
			
			-- // Tuning stuff
			exports.edf:edfSetElementProperty(source, "collisions", "false")
			exports.edf:edfSetElementProperty(source, "locked", "true")
			exports.edf:edfSetElementProperty(source, "frozen", "true")
			exports.edf:edfSetElementProperty(source, "upgrades", {1097, 1010})
			exports.edf:edfSetElementProperty(source, "plate", "TASDUMMY")
			
			-- // Set custom ID, fuckin override everything idc
			local testID = 1
			while getElementByID("TAS:Dummy ("..tostring(testID)..")") do
				testID = testID + 1
			end
			local newID = "TAS:Dummy ("..tostring(testID)..")"
			setElementID(source, newID)
			setElementData(source, "id", newID)
			setElementData(source, "me:ID", newID)
			setElementData(source, "me:autoID", true)
			exports.edf:edfSetElementProperty(source, "id", newID)
			
			-- // Pretty color
			setVehicleColor(source, 255, 0, 0, 255, 255, 255, 255, 0, 0, 255, 255, 255)
			
			-- // We finished? Hell yeah, disable this so we don't apply dummy properties
			tas.var.isCreatingDummy = false
		end
	end
end)

addEventHandler("onPlayerQuit", root, function()
	local player = source
	if tas.var.automation and tas.var.automation.player == player then
		tas.automation_fail("target player disconnected")
	end
	tas.var.cooldowns[player] = nil
	tas.var.handles[player] = nil
	tas.var.warps[player] = nil
end)

-- // Command messages
function tas.prompt(text, element, r, g, b)
	if type(text) ~= "string" then return end
	if not (r and g and b) then return end
	return outputChatBox("[SERVER-TAS] #FFFFFF"..string.gsub(string.gsub(text, "%#%#", "#FFFFFF"), "%$%$", string.format("#%.2X%.2X%.2X", r, g, b)), element, r, g, b, true)
end

function tas.float(number)
	return math.floor( number * 1000 ) * 0.001
end
