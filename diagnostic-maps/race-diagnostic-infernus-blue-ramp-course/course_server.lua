local CAR_Z = 279.89999
local stages = {
    { x=1800, y=-1580 },
    { x=1855, y=-1490 },
    { x=1910, y=-1530 },
    { x=1965, y=-1580 },
    { x=2020, y=-1580 },
}
local courseStarted = false

local function findVehicle(player, index, attempt)
    if not courseStarted or not isElement(player) or not stages[index] then return end
    local vehicle = getPedOccupiedVehicle(player)
    if not vehicle then
        if attempt < 30 then
            setTimer(findVehicle, 500, 1, player, index, attempt + 1)
        else
            outputChatBox("[DIAG] Could not find your Infernus. Use /diagstage " .. index .. " after entering it.", player, 255, 100, 100)
        end
        return
    end
    local s = stages[index]
    setElementFrozen(vehicle, true)
    fixVehicle(vehicle)
    setElementHealth(vehicle, 1000)
    setVehicleEngineState(vehicle, true)
    setVehicleNitroActivated(vehicle, false)
    setElementPosition(vehicle, s.x, s.y, CAR_Z)
    setElementRotation(vehicle, 0, 0, 0)
    setElementVelocity(vehicle, 0, 0, 0)
    setElementAngularVelocity(vehicle, 0, 0, 0)
    outputChatBox("[DIAG] Vehicle reset on the continuous test deck. Keep all controls released.", player, 255, 220, 90)
    setTimer(function()
        if not isElement(player) or not isElement(vehicle) then return end
        setElementVelocity(vehicle, 0, 0, 0)
        setElementAngularVelocity(vehicle, 0, 0, 0)
        triggerClientEvent(player, "diag:stageReady", resourceRoot, index)
    end, 1500, 1)
end

-- A Race map resource is loaded before Race's own waiting/countdown has finished.
-- Do not arm our stage until Race has actually entered Running.
addEventHandler("onRaceStateChanging", root, function(newState)
    if newState ~= "Running" or courseStarted then return end
    courseStarted = true
    setTimer(function()
        for _, player in ipairs(getElementsByType("player")) do
            findVehicle(player, 1, 0)
        end
    end, 300, 1)
end)

addEventHandler("onResourceStart", resourceRoot, function()
    outputChatBox("[DIAG] Waiting for the Race start to finish before arming the diagnostic countdown.", root, 255, 220, 90)
end)

addEvent("diag:resetStage", true)
addEventHandler("diag:resetStage", root, function(index)
    if client ~= source then return end
    if not courseStarted then
        outputChatBox("[DIAG] Race has not started yet; the diagnostic stage is intentionally waiting.", client, 255, 160, 100)
        return
    end
    index = tonumber(index)
    if not index or not stages[index] then return end
    findVehicle(client, index, 0)
end)

addEvent("diag:goStage", true)
addEventHandler("diag:goStage", root, function(index)
    if client ~= source or not courseStarted then return end
    index = tonumber(index)
    if not index or not stages[index] then return end
    local vehicle = getPedOccupiedVehicle(client)
    if not vehicle then return end
    setElementVelocity(vehicle, 0, 0, 0)
    setElementAngularVelocity(vehicle, 0, 0, 0)
    setElementFrozen(vehicle, false)
    triggerClientEvent(client, "diag:stageGo", resourceRoot, index)
end)

addEvent("diag:freezeVehicle", true)
addEventHandler("diag:freezeVehicle", root, function()
    if client ~= source then return end
    local vehicle = getPedOccupiedVehicle(client)
    if vehicle then
        setElementFrozen(vehicle, true)
        setElementVelocity(vehicle, 0, 0, 0)
        setElementAngularVelocity(vehicle, 0, 0, 0)
    end
end)
