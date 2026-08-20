-- Lightweight Lua 5.1 harness for the format-v3 telemetry helpers.
-- MTA supplies these globals at runtime; the stubs make the serializer testable
-- without pretending that this is a full game simulation.

local component_available = true
local friction_available = true

function getLocalPlayer() return "player" end
function getRootElement() return "root" end
function getFPSLimit() return 100 end
function getGameSpeed() return 1 end
function guiGetScreenSize() return 1280, 720 end
function addEventHandler() end
function addEvent() end
function addDebugHook() end
function getVehicleHandling() return {centerOfMass = {0, 0, -0.25}, steeringLock = 30} end
function getVehicleCurrentGear() return 3 end
function getVehicleWheelStates() return 0, 0, 0, 0 end
function isVehicleWheelOnGround(_, index) return index ~= 3 end
function getVehicleWheelFrictionState(_, index)
    if not friction_available then return nil end
    return index
end
function getVehicleComponentPosition(_, component, base)
    if not component_available then error("component API unavailable") end
    local x = (component == "wheel_lf_dummy" or component == "wheel_lb_dummy") and -1 or 1
    local y = (component == "wheel_lf_dummy" or component == "wheel_rf_dummy") and 2 or -2
    if base == "world" then return x + 10, y + 20, 30 end
    if base == "root" then return x, y, -0.4 end
    return 0, 0, -0.4
end
function getVehicleComponentRotation(_, _, base)
    if not component_available then error("component API unavailable") end
    if base == "world" then return 1, 2, 3 end
    if base == "root" then return 4, 5, 6 end
    return 7, 8, 9
end

local source = assert(io.open(arg[1], "rb")):read("*a")
local chunk = assert(loadstring(source .. "\nreturn tas\n"))
local tas = chunk()

local status = tas.physics_telemetry_api_status()
assert(status.getVehicleWheelFrictionState == true)
assert(status.getVehicleCurrentGear == true)
assert(status.getVehicleComponentPosition == true)
assert(status.getVehicleComponentRotation == true)

local matrix = {
    {1, 0, 0},
    {0, 1, 0},
    {0, 0, 1},
    {10, 20, 30},
}
local contacts = {
    {wheel = 1, position = {10, 20, 29}, onGround = true},
    {wheel = 2, position = {10, 20, 29}, onGround = true},
    {wheel = 3, position = {10, 20, 29}, onGround = true},
    {wheel = 4, position = {10, 20, 29}, onGround = false},
}
tas.reset_physics_telemetry_state("vehicle")
local steering_estimate_1 = tas.capture_steering_telemetry(
    {vehicle_left = true, vehicle_right = false},
    {vehicle_left = 0, vehicle_right = 0},
    {centerOfMass = {0, 0, -0.25}, steeringLock = 30}, 100
)
local steering_estimate_2 = tas.capture_steering_telemetry(
    {vehicle_left = true, vehicle_right = false},
    {vehicle_left = 0, vehicle_right = 0},
    {centerOfMass = {0, 0, -0.25}, steeringLock = 30}, 110
)
assert(steering_estimate_1.derived.target == 1)
assert(steering_estimate_1.measured.analogLeft == 0)
assert(steering_estimate_2.derived.rawSteerAngle > 0)

local steering = {derived = {steeringAngleDegrees = 7}}
local result = tas.capture_wheel_telemetry(
    "vehicle", matrix, {10, 20, 30}, {1, 2, 3}, {0, 0, 1},
    {true, true, true, false}, contacts,
    {centerOfMass = {0, 0, -0.25}, steeringLock = 30}, steering
)
assert(result.currentGear == 3)
assert(result.wheelOrder[1] == "front_left")
assert(result.wheelOrder[2] == "rear_left")
assert(result.wheelOrder[3] == "front_right")
assert(result.wheelOrder[4] == "rear_right")
assert(result.wheels.front_left.index == 0)
assert(result.wheels.rear_left.index == 1)
assert(result.wheels.front_right.index == 2)
assert(result.wheels.rear_right.index == 3)
assert(result.wheels.front_left.measured.frictionState == 0)
assert(result.wheels.rear_right.measured.onGround == false)
assert(result.wheels.front_left.measured.componentPosition.world[1] == 9)
assert(result.wheels.front_left.measured.componentRotation.root[1] == 4)
assert(result.wheels.front_left.derived.contactPointVelocityRaw ~= nil)

-- An unavailable/throwing component or friction API must leave optional fields
-- absent rather than aborting an entire playback capture.
component_available = false
friction_available = false
local missing = tas.capture_wheel_telemetry(
    "vehicle", matrix, {10, 20, 30}, {1, 2, 3}, {0, 0, 1},
    {true, true, true, true}, contacts,
    {centerOfMass = {0, 0, -0.25}}, steering
)
assert(missing.wheels.front_left.measured.componentPosition.world == nil)
assert(missing.wheels.front_left.measured.componentRotation.world == nil)
assert(missing.wheels.front_left.measured.frictionState == nil)
print("client telemetry harness: ok")
