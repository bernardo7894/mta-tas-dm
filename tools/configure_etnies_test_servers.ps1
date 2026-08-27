[CmdletBinding()]
param(
    [string]$LiveServerRoot = 'C:\Program Files (x86)\MTA San Andreas 1.6\server',
    [string]$DebugServerRoot = 'D:\Users\Bernardo\Documents\mtasa-blue\Bin\server',
    [int]$FpsLimit = 100,
    [string]$MapResource = 'race-dm-Skynetv5-EtniesII(fix)'
)
$ErrorActionPreference = 'Stop'
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$HudSource = Join-Path $RepoRoot 'new\tas\frame_hud.lua'

function Backup-Once([string]$Path, [string]$Suffix) {
    if (-not (Test-Path -LiteralPath $Path)) { throw "Missing required file: $Path" }
    $bak = $Path + $Suffix
    if (-not (Test-Path -LiteralPath $bak)) { Copy-Item -LiteralPath $Path -Destination $bak }
}
function Load-Config([string]$Path) {
    $x = New-Object System.Xml.XmlDocument; $x.PreserveWhitespace = $true; $x.Load($Path)
    if (-not $x.SelectSingleNode('/config')) { throw "Unexpected server config: $Path" }
    return $x
}
function Set-Fps($x, [int]$Value) {
    $n = $x.SelectSingleNode('/config/fpslimit')
    if (-not $n) { $n=$x.CreateElement('fpslimit'); [void]$x.DocumentElement.AppendChild($n) }
    $n.InnerText = [string]$Value
}
function Resource-Node($x, [string]$Name) {
    foreach($n in $x.SelectNodes('/config/resource')) { if($n.GetAttribute('src') -eq $Name){ return $n } }
    return $null
}
function Ensure-Startup($x, [string]$Name) {
    $n=Resource-Node $x $Name
    if(-not $n){ $n=$x.CreateElement('resource'); $n.SetAttribute('src',$Name); $n.SetAttribute('protected','0'); [void]$x.DocumentElement.AppendChild($n) }
    $n.SetAttribute('startup','1')
}
function Disable-If-Present($x, [string]$Name) {
    $n=Resource-Node $x $Name; if($n){ $n.SetAttribute('startup','0') }
}

function Patch-TasHud([string]$ServerRoot) {
    if(-not (Test-Path -LiteralPath $HudSource)){ throw "HUD source missing: $HudSource" }
    $tas=Join-Path $ServerRoot 'mods\deathmatch\resources\tas'
    $meta=Join-Path $tas 'meta.xml'
    Backup-Once $meta '.pre-source-frame-hud.bak'
    $enc=New-Object Text.UTF8Encoding($false)
    $mt=[IO.File]::ReadAllText($meta)
    if($mt -notmatch 'frame_hud\.lua'){
        $m=[regex]::Match($mt,'(?m)^[ \t]*<script src="client\.lua" type="client" cache="false" />[ \t]*\r?\n')
        if(!$m.Success){ throw "client.lua meta anchor missing: $meta" }
        $nl=if($m.Value.EndsWith("`r`n")){"`r`n"}else{"`n"}
        $mt=$mt.Insert($m.Index+$m.Length,'    <script src="frame_hud.lua" type="client" cache="false" />'+$nl)
        [IO.File]::WriteAllText($meta,$mt,$enc)
    }
    Copy-Item -LiteralPath $HudSource -Destination (Join-Path $tas 'frame_hud.lua') -Force
    Write-Host "HUD patched without replacing TAS client variant: $tas"
}

function Install-Startup([string]$ServerRoot, [string]$MapName) {
    $d=Join-Path $ServerRoot 'mods\deathmatch\resources\etnies-startup'
    New-Item -ItemType Directory -Path $d -Force | Out-Null
    $enc=New-Object Text.UTF8Encoding($false)
    $meta=@'
<meta>
    <info author="local" name="Etnies test startup" type="script" />
    <include resource="mapmanager" />
    <script src="server.lua" type="server" />
</meta>
'@
    [IO.File]::WriteAllText((Join-Path $d 'meta.xml'),$meta,$enc)
    $escaped=$MapName.Replace("'","\'")
    $lua=@"
local targetMapName = '$escaped'
local attempts = 0
local function isTargetRunning()
    local okMode, mode = pcall(function() return exports.mapmanager:getRunningGamemode() end)
    local okMap, map = pcall(function() return exports.mapmanager:getRunningGamemodeMap() end)
    return okMode and okMap and mode and map
        and getResourceName(mode) == 'race' and getResourceName(map) == targetMapName
end
local function startEtnies()
    attempts = attempts + 1
    if isTargetRunning() then return end
    local manager = getResourceFromName('mapmanager')
    if manager and getResourceState(manager) == 'running' then
        local ok, changed = pcall(function()
            return exports.mapmanager:changeGamemodeByName('race', targetMapName, true)
        end)
        if ok and changed then
            outputDebugString('[etnies-startup] requested Race + ' .. targetMapName)
            return
        end
    end
    if attempts < 60 then setTimer(startEtnies, 500, 1)
    else outputDebugString('[etnies-startup] failed to start Race + ' .. targetMapName, 1) end
end
addEventHandler('onResourceStart', resourceRoot, function() setTimer(startEtnies, 500, 1) end)
"@
    [IO.File]::WriteAllText((Join-Path $d 'server.lua'),$lua,$enc)
}

function Find-Map([string]$ServerRoot, [string]$Name) {
    $resources=Join-Path $ServerRoot 'mods\deathmatch\resources'
    $matches=@(Get-ChildItem -LiteralPath $resources -Directory -Recurse | Where-Object { $_.Name -eq $Name })
    if($matches.Count -eq 0){ throw "Map resource '$Name' not found under $resources" }
    foreach($m in $matches){ Write-Host "Map resource: $($m.FullName)" }
}

$liveConfig=Join-Path $LiveServerRoot 'mods\deathmatch\mtaserver.conf'
$debugConfig=Join-Path $DebugServerRoot 'mods\deathmatch\mtaserver.conf'

Find-Map $LiveServerRoot $MapResource
Find-Map $DebugServerRoot $MapResource

Backup-Once $liveConfig '.pre-etnies-test.bak'
$live=Load-Config $liveConfig
Set-Fps $live $FpsLimit
Ensure-Startup $live 'mapmanager'
Ensure-Startup $live 'tas'
Ensure-Startup $live 'etnies-startup'
# Let mapmanager start Race atomically with the requested map. Do not boot bare Race.
Disable-If-Present $live 'race'
Disable-If-Present $live 'play'
$live.Save($liveConfig)
Write-Host "Configured live server: fpslimit=$FpsLimit"

$debug=Load-Config $debugConfig
$debugFps=$debug.SelectSingleNode('/config/fpslimit')
if(-not $debugFps -or $debugFps.InnerText -ne [string]$FpsLimit){
    Backup-Once $debugConfig '.pre-etnies-test.bak'
    Set-Fps $debug $FpsLimit
    $debug.Save($debugConfig)
    Write-Host "Configured debug server: fpslimit=$FpsLimit"
} else {
    Write-Host "Debug server already uses fpslimit=$FpsLimit; other settings preserved"
}

# The two deployments intentionally keep their existing client.lua variants.
# Only the meta entry/HUD file are added; client.lua is never rewritten.
Patch-TasHud $LiveServerRoot
Patch-TasHud $DebugServerRoot
Install-Startup $LiveServerRoot $MapResource

Write-Host ''
Write-Host "Done. Both server configs use fpslimit=$FpsLimit."
Write-Host "The normal server boots Race with $MapResource through etnies-startup."
Write-Host 'The debug/native server keeps its existing play/capture configuration.'
Write-Host 'The source-frame HUD defaults on; /tascvar showPlaybackFrameHud false persists normally.'
