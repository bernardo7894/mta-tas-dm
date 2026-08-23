local CAR_Z = 279.89999
local stages = {
    { x=1800, y=-1580 },
    { x=1855, y=-1490 },
    { x=1910, y=-1530 },
    { x=1965, y=-1580 },
    { x=2020, y=-1580 },
}
local vehicles = {}

local function getOrCreateVehicle(player)
    if isPedDead(player) then
        spawnPlayer(player, stages[1].x, stages[1].y, CAR_Z + 1.0, 0, 0)
    end
    local vehicle = getPedOccupiedVehicle(player)
    if vehicle and getElementModel(vehicle) == 411 then
        vehicles[player] = vehicle
        return vehicle
    end
    vehicle = vehicles[player]
    if not isElement(vehicle) then
        vehicle = createVehicle(411, stages[1].x, stages[1].y, CAR_Z, 0, 0, 0)
        vehicles[player] = vehicle
    end
    if isPedInVehicle(player) then removePedFromVehicle(player) end
    warpPedIntoVehicle(player, vehicle)
    return vehicle
end

local function resetStage(player, index)
    if not isElement(player) or not stages[index] then return end
    local vehicle = getOrCreateVehicle(player)
    if not isElement(vehicle) then return end
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
    setCameraTarget(player, player)
    outputChatBox("[DIAG] Vehicle reset on the continuous test deck. Keep all controls released.", player, 255, 220, 90)
    setTimer(function()
        if not isElement(player) or not isElement(vehicle) then return end
        setElementVelocity(vehicle, 0, 0, 0)
        setElementAngularVelocity(vehicle, 0, 0, 0)
        triggerClientEvent(player, "waterdiag:stageReady", resourceRoot, index)
    end, 1500, 1)
end

addEvent("waterdiag:clientReady", true)
addEventHandler("waterdiag:clientReady", root, function()
    if client ~= source then return end
    resetStage(client, 1)
end)

addEvent("waterdiag:resetStage", true)
addEventHandler("waterdiag:resetStage", root, function(index)
    if client ~= source then return end
    index = tonumber(index)
    if not index or not stages[index] then return end
    resetStage(client, index)
end)

addEvent("waterdiag:goStage", true)
addEventHandler("waterdiag:goStage", root, function(index)
    if client ~= source then return end
    index = tonumber(index)
    if not index or not stages[index] then return end
    local vehicle = getOrCreateVehicle(client)
    if not vehicle then return end
    setElementVelocity(vehicle, 0, 0, 0)
    setElementAngularVelocity(vehicle, 0, 0, 0)
    setElementFrozen(vehicle, false)
    triggerClientEvent(client, "waterdiag:stageGo", resourceRoot, index)
end)

addEvent("waterdiag:freezeVehicle", true)
addEventHandler("waterdiag:freezeVehicle", root, function()
    if client ~= source then return end
    local vehicle = getPedOccupiedVehicle(client)
    if vehicle then
        setElementFrozen(vehicle, true)
        setElementVelocity(vehicle, 0, 0, 0)
        setElementAngularVelocity(vehicle, 0, 0, 0)
    end
end)

addEventHandler("onPlayerQuit", root, function()
    local vehicle = vehicles[source]
    if isElement(vehicle) then destroyElement(vehicle) end
    vehicles[source] = nil
end)

addEventHandler("onResourceStart", resourceRoot, function()
    setGameType("Infernus Physics Diagnostic")
    setMapName("Waterjump stages")
    setTime(12, 0)
    setWeather(0)
    setGameSpeed(1)
    setGravity(0.008)
end)
