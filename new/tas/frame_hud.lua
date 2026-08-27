-- Source-frame HUD for TAS playback comparison.
--
-- This is deliberately separate from the normal /debugr HUD.  It shows the
-- source TAS frame being consumed by playback, which makes ordinary
-- state-forced playback and controls-only/native playback videos directly
-- comparable by eye.  It does not change playback timing, controls, or
-- vehicle state.

local tas = getTASData()
if not tas then
    return
end

-- Top-level settings are automatically exposed by /tascvar and persisted by
-- the existing @config.json machinery.  Make this visible by default while
-- still allowing `/tascvar showPlaybackFrameHud false`.
if tas.settings.showPlaybackFrameHud == nil then
    tas.settings.showPlaybackFrameHud = true
end

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

    -- A compact top-centre label stays readable in captured video without
    -- overlapping the normal TAS control/debug HUD near the bottom.
    dxDrawText(text, 1, 45, screenW + 1, 73, tocolor(0, 0, 0, 220), 1.15, "default-bold", "center", "top")
    dxDrawText(text, 0, 44, screenW, 72, tocolor(255, 255, 255, 240), 1.15, "default-bold", "center", "top")
end

addEventHandler("onClientRender", root, drawSourceFrameHud, true, "low+10")
