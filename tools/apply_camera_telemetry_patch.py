from pathlib import Path

path = Path("new/tas/client.lua")
raw = path.read_bytes()
newline = "\r\n" if b"\r\n" in raw else "\n"
text = raw.decode("utf-8").replace("\r\n", "\n")


def replace_once(old, new, label):
    global text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    text = text.replace(old, new, 1)


replace_once(
    '\tsave_analysis = "savephysics",\n\tsave_both = "saveboth",\n',
    '\tsave_analysis = "savephysics",\n\tsave_camera = "savecamera",\n\tsave_both = "saveboth",\n\tsave_all = "saveall",\n',
    "registered camera/saveall commands",
)

camera_helpers = r'''
-- // Camera reference telemetry. This is sampled from record_state so camera,
-- // controls and vehicle state share the exact same TAS source frame.
function tas.camera_world_to_vehicle_local(matrix, point)
	if not matrix or not point or not matrix[1] or not matrix[2] or not matrix[3] or not matrix[4] then return nil end
	local dx = point[1] - matrix[4][1]
	local dy = point[2] - matrix[4][2]
	local dz = point[3] - matrix[4][3]
	return {
		dx * matrix[1][1] + dy * matrix[1][2] + dz * matrix[1][3],
		dx * matrix[2][1] + dy * matrix[2][2] + dz * matrix[2][3],
		dx * matrix[3][1] + dy * matrix[3][2] + dz * matrix[3][3],
	}
end

function tas.capture_camera_state(vehicle, matrix)
	local cx, cy, cz, lx, ly, lz, roll, fov = getCameraMatrix()
	if not cx then return nil end

	local camera_position = {cx, cy, cz}
	local look_at = {lx, ly, lz}
	local vehicle_matrix = matrix or (vehicle and getElementMatrix(vehicle, false)) or nil
	local target = getCameraTarget()
	local target_info = nil
	if target and isElement(target) then
		target_info = {
			elementType = getElementType(target),
			model = getElementModel(target),
			isLocalPlayer = target == localPlayer,
			isRecordedVehicle = target == vehicle,
		}
	end

	local vehicle_position = nil
	local distance_to_vehicle = nil
	if vehicle and isElement(vehicle) then
		local vx, vy, vz = getElementPosition(vehicle)
		vehicle_position = {vx, vy, vz}
		local dx, dy, dz = cx - vx, cy - vy, cz - vz
		distance_to_vehicle = math.sqrt(dx * dx + dy * dy + dz * dz)
	end

	return {
		position = camera_position,
		lookAt = look_at,
		roll = roll,
		fov = fov,
		target = target_info,
		vehiclePosition = vehicle_position,
		distanceToVehicle = distance_to_vehicle,
		relativeToVehicle = vehicle_matrix and {
			position = tas.camera_world_to_vehicle_local(vehicle_matrix, camera_position),
			lookAt = tas.camera_world_to_vehicle_local(vehicle_matrix, look_at),
		} or nil,
	}
end

'''
replace_once(
    '-- // Recording vehicle state\nfunction tas.record_state(vehicle)\n',
    camera_helpers + '-- // Recording vehicle state\nfunction tas.record_state(vehicle)\n',
    "camera helper insertion",
)
replace_once(
    '\t\tlocal steering_telemetry = tas.capture_steering_telemetry(controls, analog_controls, tas.var.physics_handling, current_tick)\n\t\tlocal analysis = {\n',
    '\t\tlocal steering_telemetry = tas.capture_steering_telemetry(controls, analog_controls, tas.var.physics_handling, current_tick)\n\t\tlocal camera = tas.capture_camera_state(vehicle, matrix)\n\t\tlocal analysis = {\n',
    "camera sample in record_state",
)
replace_once(
    '\t\treturn real_time, p, r, v, rv, health, model, nos, keys, ground, analog, analysis\n',
    '\t\treturn real_time, p, r, v, rv, health, model, nos, keys, ground, analog, analysis, camera\n',
    "record_state camera return",
)
replace_once(
    '\tlocal _, live_p, live_r, live_v, live_rv, _, _, _, _, _, _, analysis = tas.record_state(vehicle)\n',
    '\tlocal _, live_p, live_r, live_v, live_rv, _, _, _, _, _, _, analysis, camera = tas.record_state(vehicle)\n',
    "playback camera return capture",
)
replace_once(
    '\tframe_data.x = frame_data.x or {}\n\tframe_data.x.matrix = analysis.matrix\n',
    '\tframe_data.x = frame_data.x or {}\n\tframe_data.c = camera\n\tframe_data.x.matrix = analysis.matrix\n',
    "playback camera frame storage",
)
replace_once(
    '\t\tlocal tick, p, r, v, rv, health, model, nos, keys, ground, analog, analysis = tas.record_state(vehicle)\n',
    '\t\tlocal tick, p, r, v, rv, health, model, nos, keys, ground, analog, analysis, camera = tas.record_state(vehicle)\n',
    "recording camera return capture",
)
replace_once(
    '\t\t\tx = analysis, -- extended physics-analysis state; ignored by normal TAS playback\n\t\t\tmarked = marked,\n',
    '\t\t\tx = analysis, -- extended physics-analysis state; ignored by normal TAS playback\n\t\t\tc = camera, -- camera reference state; saved separately as .camera.jsonl\n\t\t\tmarked = marked,\n',
    "recording camera frame storage",
)
replace_once(
    '\tif name then\n\t\texecuteCommandHandler(tas.registered_commands.save_analysis, name)\n\tend\n',
    '\tif name then\n\t\texecuteCommandHandler(tas.registered_commands.save_analysis, name)\n\t\texecuteCommandHandler(tas.registered_commands.save_camera, name)\n\tend\n',
    "recordplayback auto-save camera",
)
replace_once(
    '\tlocal outputFile = (tas.settings.usePrivateFolder == true and "@" or "") .. "saves/" .. automation.outputName .. ".physics.jsonl"\n\tif fileExists(outputFile) then fileDelete(outputFile) end\n',
    '\tlocal outputFile = (tas.settings.usePrivateFolder == true and "@" or "") .. "saves/" .. automation.outputName .. ".physics.jsonl"\n\tlocal cameraOutputFile = (tas.settings.usePrivateFolder == true and "@" or "") .. "saves/" .. automation.outputName .. ".camera.jsonl"\n\tif fileExists(outputFile) then fileDelete(outputFile) end\n\tif fileExists(cameraOutputFile) then fileDelete(cameraOutputFile) end\n',
    "automation camera cleanup",
)
replace_once(
    '\t\tlocal outputFile = (tas.settings.usePrivateFolder == true and "@" or "") .. "saves/" .. name .. ".physics.jsonl"\n\t\tlocal saved = completed ~= false and fileExists(outputFile)\n\t\tlocal state = saved and "completed" or (completed == false and "cancelled" or "failed")\n\t\tlocal message = saved and "Playback capture saved" or (completed == false and "Playback capture stopped" or "Physics export was not created")\n',
    '\t\tlocal outputFile = (tas.settings.usePrivateFolder == true and "@" or "") .. "saves/" .. name .. ".physics.jsonl"\n\t\tlocal cameraOutputFile = (tas.settings.usePrivateFolder == true and "@" or "") .. "saves/" .. name .. ".camera.jsonl"\n\t\tlocal saved = completed ~= false and fileExists(outputFile) and fileExists(cameraOutputFile)\n\t\tlocal state = saved and "completed" or (completed == false and "cancelled" or "failed")\n\t\tlocal message = saved and "Playback physics + camera capture saved" or (completed == false and "cancelled" or "Physics/camera export was not created")\n',
    "automation camera completion check",
)

save_all_block = r'''
	-- // Save All (legacy TAS + physics + camera)
	elseif cmd == tas.registered_commands.save_all then

		if args[1] == nil then
			tas.prompt("Saving all failed, please specify a $$name ##for your files!", 255, 100, 100)
			tas.prompt("Example: $$/saveall infernus_reference", 255, 100, 100)
			return
		end
		if #tas.data == 0 then tas.prompt("Saving failed, no $$data ##recorded!", 255, 100, 100) return end

		executeCommandHandler(tas.registered_commands.save_record, args[1])
		executeCommandHandler(tas.registered_commands.save_analysis, args[1])
		executeCommandHandler(tas.registered_commands.save_camera, args[1])

'''
replace_once(
    '\texecuteCommandHandler(tas.registered_commands.save_record, args[1])\n\texecuteCommandHandler(tas.registered_commands.save_analysis, args[1])\n\n\t-- // Save Physics Analysis\n',
    '\texecuteCommandHandler(tas.registered_commands.save_record, args[1])\n\texecuteCommandHandler(tas.registered_commands.save_analysis, args[1])\n\n' + save_all_block + '\t-- // Save Physics Analysis\n',
    "saveall command block",
)

camera_save_block = r'''
	-- // Save Camera Reference
	elseif cmd == tas.registered_commands.save_camera then

		if args[1] == nil then
			tas.prompt("Camera export failed, please specify a $$name ##for your file!", 255, 100, 100)
			tas.prompt("Example: $$/savecamera infernus_reference", 255, 100, 100)
			return
		end
		if #tas.data == 0 then tas.prompt("Camera export failed, no $$data ##recorded!", 255, 100, 100) return end

		local isPrivated = (tas.settings.usePrivateFolder == true and "@") or ""
		local fileTarget = isPrivated .. "saves/" .. args[1] .. ".camera.jsonl"

		if tas.settings.useWarnings then
			if fileExists(fileTarget) and not tas.timers.warnCameraSave then
				tas.timers.warnCameraSave = setTimer(function() tas.timers.warnCameraSave = nil end, 5000, 1)
				tas.prompt("Existing camera export $$'"..args[1]..".camera.jsonl' ##found! Use the command again to overwrite it.", 255, 100, 100)
				return
			end
		end

		local save_file = fileCreate(fileTarget)
		if not save_file then
			tas.prompt("Camera export failed, couldn't create $$'"..fileTarget.."'##!", 255, 100, 100)
			return
		end

		local frame_limit = tas.analysis.export_frame_limit or #tas.data
		local recorded_at = tas.analysis.metadata and tas.analysis.metadata.recordedAtUtc or os.date("!%Y-%m-%dT%H:%M:%SZ")
		local metadata = {
			format = "mta-tas-dm-camera-jsonl",
			formatVersion = 1,
			recordedAtUtc = recorded_at,
			frameCount = frame_limit,
			author = string_gsub(getPlayerName(localPlayer), "#%x%x%x%x%x%x", ""),
			source = "getCameraMatrix sampled inside TAS record_state",
			synchronizedBy = "TAS source frame and tick",
		}
		local metadata_line = tas.json_object({type = "metadata", data = metadata})
		if metadata_line then fileWrite(save_file, metadata_line .. "\n") end

		local written = 0
		for i=1, frame_limit do
			local run = tas.data[i]
			if run and run.c then
				local line = tas.json_object({type = "frame", frame = i, tick = run.tick, camera = run.c})
				if line then
					fileWrite(save_file, line .. "\n")
					written = written + 1
				end
			end
		end

		fileClose(save_file)
		tas.timers.warnCameraSave = nil
		if written ~= frame_limit then
			tas.prompt("Camera telemetry saved, but only $$"..written.."/"..frame_limit.." ##frames contained camera samples.", 255, 180, 100)
		else
			tas.prompt("Camera telemetry saved ".. (tas.settings.usePrivateFolder == true and "$$privately ##" or "") .. "to $$'saves/"..args[1]..".camera.jsonl'##!", 255, 255, 100)
		end

'''
replace_once(
    '\t\ttas.prompt("Physics telemetry saved ".. (tas.settings.usePrivateFolder == true and "$$privately ##" or "") .. "to $$\'saves/"..args[1]..".physics.jsonl\'##!", 255, 255, 100)\n\t\n\t-- // Load Recording\n',
    '\t\ttas.prompt("Physics telemetry saved ".. (tas.settings.usePrivateFolder == true and "$$privately ##" or "") .. "to $$\'saves/"..args[1]..".physics.jsonl\'##!", 255, 255, 100)\n\t\n' + camera_save_block + '\t-- // Load Recording\n',
    "savecamera command block",
)
replace_once(
    '\t\t\t"/"..tas.registered_commands.save_analysis.." [name] $$- ##export extended physics telemetry (JSONL)",\n\t\t\t"/"..tas.registered_commands.save_both.." [name] $$- ##save both TAS and physics files",\n',
    '\t\t\t"/"..tas.registered_commands.save_analysis.." [name] $$- ##export extended physics telemetry (JSONL)",\n\t\t\t"/"..tas.registered_commands.save_camera.." [name] $$- ##export synchronized camera telemetry (JSONL)",\n\t\t\t"/"..tas.registered_commands.save_both.." [name] $$- ##save TAS and physics files (legacy behavior)",\n\t\t\t"/"..tas.registered_commands.save_all.." [name] $$- ##save TAS, physics and camera files",\n',
    "help text",
)

path.write_bytes(text.replace("\n", newline).encode("utf-8"))

docs = Path("new/tas/PHYSICS_EXPORT.md")
d_raw = docs.read_bytes()
d_nl = "\r\n" if b"\r\n" in d_raw else "\n"
d = d_raw.decode("utf-8").replace("\r\n", "\n")
heading = "# Physics analysis export\n"
addition = '''# Physics analysis export\n\n## Separate synchronized camera export\n\nCamera telemetry is deliberately stored separately from physics telemetry. Every TAS source frame samples `getCameraMatrix()` from the same `record_state()` call as vehicle state and controls, then `/savecamera <name>` writes `<name>.camera.jsonl`. Each camera frame carries the same source frame number and TAS tick, plus camera position, look-at point, roll, FOV, target metadata, distance to the recorded vehicle, and vehicle-local camera/look-at coordinates.\n\nCommands:\n\n- `/savecamera <name>` saves only `<name>.camera.jsonl`.\n- `/saveboth <name>` remains backward-compatible and saves only `<name>.tas` + `<name>.physics.jsonl`.\n- `/saveall <name>` saves the TAS, physics, and camera files.\n- `/recordplayback <name>` refreshes both `<name>.physics.jsonl` and `<name>.camera.jsonl` from the replayed source frames.\n\nThe camera stream is not embedded in `.physics.jsonl`, and the legacy `.tas` serialization is unchanged.\n'''
if "## Separate synchronized camera export" not in d:
    if not d.startswith(heading):
        raise SystemExit("PHYSICS_EXPORT heading not found")
    d = d.replace(heading, addition, 1)
    docs.write_bytes(d.replace("\n", d_nl).encode("utf-8"))

readme = Path("new/tas/README.md")
r_raw = readme.read_bytes()
r_nl = "\r\n" if b"\r\n" in r_raw else "\n"
r = r_raw.decode("utf-8").replace("\r\n", "\n")
note = "\nCamera reference telemetry can be exported separately with `/savecamera <name>` (`<name>.camera.jsonl`), while `/saveall <name>` saves TAS + physics + camera. `/saveboth` keeps its legacy TAS + physics behavior.\n"
if "`/savecamera <name>`" not in r:
    r = r.rstrip() + "\n" + note
    readme.write_bytes(r.replace("\n", r_nl).encode("utf-8"))
