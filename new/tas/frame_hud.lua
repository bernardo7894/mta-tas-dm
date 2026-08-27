-- Source-frame HUD for TAS playback comparison.
--
-- Shows the source TAS frame currently being consumed by playback so ordinary
-- state-forced playback and controls-only/native playback videos can be
-- compared by source frame instead of wall-clock/video timing. This is display
-- only and does not modify playback timing, controls, or vehicle state.

local tas = getTASData()
if not tas then
    return
end

-- client.lua loads @config.json before this separate script executes. Register
-- this late-added setting here, then mirror the existing config loader for this
-- one key so `/tascvar showPlaybackFrameHud false` persists without requiring
-- any edit to the normal or native-capture client.lua variants.
local function loadHudSetting()
    if tas.settings.showPlaybackFrameHud == nil then
        tas.settings.showPlaybackFrameHud = true
    end

    if not fileExists("@config.json") then return end
    local configFile = fileOpen("@config.json")
    if not configFile then return end

    local size = fileGetSize(configFile)
    local data = fileRead(configFile, size)
    fileClose(configFile)

    local config = fromJSON(data)
    if type(config) == "table"
        and config.enableUserConfig == true
        and type(config.showPlaybackFrameHud) == "boolean" then
        tas.settings.showPlaybackFrameHud = config.showPlaybackFrameHud
    end
end

loadHudSetting()

local screenW = guiGetScreenSize()

local function formatSourceTime(milliseconds)
    milliseconds = tonumber(milliseconds) or 0
    if milliseconds < 0 then milliseconds = 0 end

    local minutes = math.floor(milliseconds / 60000)
    local seconds = math.floor(milliseconds / 1000) % 60
    local millis = math.floor(milliseconds % 1000)
    return string.format("%02d:%02d.%03d", minutes, seconds, millis)
end

local function drawSourceFrameHud()
    if tas.settings.showPlaybackFrameHud ~= true or tas.var.playbacking ~= true then
        return
    end

    local frame = tonumber(tas.var.play_frame)
    if not frame then return end

    local source = tas.data[frame]
    if not source then return end

    local text = string.format(
        "TAS SOURCE  %d / %d   |   %s",
        frame,
        #tas.data,
        formatSourceTime(source.tick)
    )

    -- Compact top-centre label, away from the existing TAS controls/debug HUD.
    dxDrawText(text, 1, 45, screenW + 1, 73, tocolor(0, 0, 0, 220), 1.15, "default-bold", "center", "top")
    dxDrawText(text, 0, 44, screenW, 72, tocolor(255, 255, 255, 240), 1.15, "default-bold", "center", "top")
end

-- Playback may run on onClientRender or onClientPreRender. Drawing at low
-- render priority makes the label reflect the source frame most recently
-- applied by either path.
addEventHandler("onClientRender", root, drawSourceFrameHud, true, "low+10")
