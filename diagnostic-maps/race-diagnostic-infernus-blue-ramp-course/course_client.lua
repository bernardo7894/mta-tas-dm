local PLATFORM_TOP_Z = 279.22848
local FINISH_Y = -1338
local stages = {
    {name='Flat baseline',x=1800,save='diag-flat',instruction='Hold W only from GO. No steering, brake, handbrake or nitro.'},
    {name='Blue waterjump - short approach',x=1855,save='diag-ramp-short',instruction='Hold W only from GO. Short approach sets the lower speed; do not steer or lift.'},
    {name='Blue waterjump - medium approach',x=1910,save='diag-ramp-medium',instruction='Hold W only from GO. Do not steer, brake, handbrake, lift or use nitro.'},
    {name='Blue waterjump - long approach',x=1965,save='diag-ramp-long',instruction='Hold W only from GO and keep it held through takeoff and landing.'},
    {name='Blue waterjump - long repeat',x=2020,save='diag-ramp-long-repeat',instruction='Repeat the long run: hold W only and do not steer.'},
}
local currentStage,stageActive,hitLocked=1,false,false
local finishMarker,finishCol,currentSaveName
local fallingRetry=false
local warningsDisabled=false

local function chat(text,r,g,b) outputChatBox('[DIAG] '..text,r or 230,g or 230,b or 230) end
local function vehicle() local v=getPedOccupiedVehicle(localPlayer); if v and getElementModel(v)==411 then return v end end
local function vehicleIsOurs(e) local v=vehicle(); return e==localPlayer or (v and e==v) end
local function destroyFinish()
    if isElement(finishMarker) then destroyElement(finishMarker) end
    if isElement(finishCol) then destroyElement(finishCol) end
    finishMarker,finishCol=nil,nil
end
local function tasReady()
    local r=getResourceFromName('tas')
    return r and getResourceState(r)=='running'
end
local function disableTasWarnings()
    if warningsDisabled then return end
    executeCommandHandler('tascvar','useWarnings','false')
    warningsDisabled=true
end
local function restoreTasWarnings()
    if not warningsDisabled then return end
    executeCommandHandler('tascvar','useWarnings','true')
    warningsDisabled=false
end
local function printStage()
    local s=stages[currentStage]
    chat(('Stage %d/%d: %s'):format(currentStage,#stages,s.name),80,220,255)
    chat(s.instruction,255,255,255)
    chat('TAS recording is automatic. Drive through the yellow FINISH marker after the run.',255,235,150)
end
local function createFinish()
    destroyFinish(); local s=stages[currentStage]
    finishMarker=createMarker(s.x,FINISH_Y,PLATFORM_TOP_Z+0.45,'cylinder',6,255,190,0,170)
    finishCol=createColCuboid(s.x-8,FINISH_Y-8,PLATFORM_TOP_Z-3,16,16,10)
    addEventHandler('onClientColShapeHit',finishCol,function(e,dim)
        if dim and vehicleIsOurs(e) and stageActive and not hitLocked then
            hitLocked=true; stageActive=false
            triggerServerEvent('diag:freezeVehicle',localPlayer)
            chat('FINISH reached - stopping TAS and saving both files...',255,220,90)
            executeCommandHandler('record')
            setTimer(function()
                executeCommandHandler('saveboth',currentSaveName)
                chat('Saved '..currentSaveName..'.tas and .physics.jsonl',120,255,140)
            end,250,1)
            destroyFinish()
            if currentStage<#stages then
                chat('Resetting for the next stage. Release ALL controls.',255,220,90)
                setTimer(function() triggerServerEvent('diag:resetStage',localPlayer,currentStage+1) end,3000,1)
            else
                restoreTasWarnings()
                chat('Course complete. All five recordings are saved.',120,255,140)
            end
        end
    end)
end

local function retryStage(reason)
    if fallingRetry or not stageActive then return end
    fallingRetry=true; stageActive=false; hitLocked=true
    executeCommandHandler('record')
    destroyFinish(); triggerServerEvent('diag:freezeVehicle',localPlayer)
    chat(reason..' Retrying this stage; the failed take is NOT saved.',255,120,80)
    setTimer(function()
        fallingRetry=false; hitLocked=false
        triggerServerEvent('diag:resetStage',localPlayer,currentStage)
    end,1800,1)
end

local function startTasRecording(index)
    currentStage=index; hitLocked=false; fallingRetry=false
    if not tasReady() then
        chat("ERROR: start/restart the updated 'tas' resource, then restart this map.",255,80,80)
        return
    end
    disableTasWarnings()
    executeCommandHandler('clearall')
    executeCommandHandler('record')
    currentSaveName=stages[index].save..'-'..os.date('%Y%m%d-%H%M%S')
    stageActive=true; createFinish(); printStage()
    chat('Recording started with a stationary pre-roll. Keep controls released.',255,220,90)
    local count=3
    local timer
    timer=setTimer(function()
        if not stageActive then if isTimer(timer) then killTimer(timer) end return end
        if count>0 then chat(tostring(count)..'...',255,220,100); count=count-1; return end
        triggerServerEvent('diag:goStage',localPlayer,currentStage)
    end,1000,4)
end

addEvent('diag:stageReady',true)
addEventHandler('diag:stageReady',resourceRoot,function(index) startTasRecording(index) end)
addEvent('diag:stageGo',true)
addEventHandler('diag:stageGo',resourceRoot,function(index)
    if tonumber(index)==currentStage and stageActive then chat('GO - perform the stage now.',120,255,140) end
end)

addEventHandler('onClientPreRender',root,function()
    if not stageActive or fallingRetry then return end
    local v=vehicle(); if not v then return end
    local _,_,z=getElementPosition(v)
    if z<265 then retryStage('You fell below the test platform.') end
end)

addEventHandler('onClientResourceStart',resourceRoot,function()
    chat('Waterjump diagnostic course loaded.',80,220,255)
    chat('Waiting for the Race gamemode to finish its own start before the diagnostic stage arms.',255,220,90)
    chat('Every lane now has a continuous vgncarshade1 deck underneath the ramp.',80,220,255)
    chat('/diagstage 1-5 jumps to a stage; /diagretry retries the current one.',255,235,150)
end)
addEventHandler('onClientResourceStop',resourceRoot,function() restoreTasWarnings() end)

addCommandHandler('diaginstructions',function() printStage() end)
addCommandHandler('diagretry',function() retryStage('Manual retry requested.') end)
addCommandHandler('diagstage',function(_,value)
    local index=tonumber(value)
    if not index or index<1 or index>#stages then chat('Usage: /diagstage 1-'..#stages,255,160,100); return end
    if stageActive then executeCommandHandler('record'); stageActive=false end
    destroyFinish(); triggerServerEvent('diag:freezeVehicle',localPlayer)
    setTimer(function() triggerServerEvent('diag:resetStage',localPlayer,index) end,500,1)
end)
