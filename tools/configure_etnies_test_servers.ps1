[CmdletBinding()]
param(
    [string]$LiveServerRoot = 'C:\Program Files (x86)\MTA San Andreas 1.6\server',
    [string]$DebugServerRoot = 'D:\Users\Bernardo\Documents\mtasa-blue\Bin\server',
    [int]$FpsLimit = 100,
    [string]$MapResource = 'race-dm-Skynetv5-EtniesII(fix)'
)

$ErrorActionPreference = 'Stop'
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$TasSource = Join-Path $RepoRoot 'new\tas'

function Backup-FileOnce {
    param([Parameter(Mandatory)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { throw "Required file does not exist: $Path" }

    $backup = "$Path.pre-etnies-test.bak"
    if (-not (Test-Path -LiteralPath $backup)) {
        Copy-Item -LiteralPath $Path -Destination $backup
        Write-Host "Backup: $backup"
    }
}

function Load-ServerConfig {
    param([Parameter(Mandatory)][string]$Path)
    Backup-FileOnce -Path $Path

    $doc = New-Object System.Xml.XmlDocument
    $doc.PreserveWhitespace = $true
    $doc.Load($Path)
    if (-not $doc.SelectSingleNode('/config')) { throw "Unexpected MTA server config structure: $Path" }
    return $doc
}

function Set-FpsLimit {
    param(
        [Parameter(Mandatory)][System.Xml.XmlDocument]$Document,
        [Parameter(Mandatory)][int]$Value
    )

    $node = $Document.SelectSingleNode('/config/fpslimit')
    if (-not $node) {
        $node = $Document.CreateElement('fpslimit')
        [void]$Document.DocumentElement.AppendChild($node)
    }
    $node.InnerText = [string]$Value
}

function Ensure-StartupResource {
    param(
        [Parameter(Mandatory)][System.Xml.XmlDocument]$Document,
        [Parameter(Mandatory)][string]$Name,
        [bool]$Startup = $true,
        [bool]$Protected = $false
    )

    $node = $null
    foreach ($candidate in $Document.SelectNodes('/config/resource')) {
        if ($candidate.GetAttribute('src') -eq $Name) {
            $node = $candidate
            break
        }
    }

    if (-not $node) {
        $node = $Document.CreateElement('resource')
        $node.SetAttribute('src', $Name)
        [void]$Document.DocumentElement.AppendChild($node)
    }

    $node.SetAttribute('startup', $(if ($Startup) { '1' } else { '0' }))
    $node.SetAttribute('protected', $(if ($Protected) { '1' } else { '0' }))
}

function Save-ServerConfig {
    param(
        [Parameter(Mandatory)][System.Xml.XmlDocument]$Document,
        [Parameter(Mandatory)][string]$Path
    )
    $Document.Save($Path)
    Write-Host "Configured: $Path"
}

function Mirror-TasResource {
    param([Parameter(Mandatory)][string]$ServerRoot)

    if (-not (Test-Path -LiteralPath $TasSource)) { throw "TAS source resource is missing: $TasSource" }

    $resources = Join-Path $ServerRoot 'mods\deathmatch\resources'
    if (-not (Test-Path -LiteralPath $resources)) { throw "MTA resources directory is missing: $resources" }

    $destination = Join-Path $resources 'tas'
    & robocopy $TasSource $destination /MIR /R:2 /W:2 | Out-Host
    if ($LASTEXITCODE -ge 8) { throw "robocopy failed for $destination (exit code $LASTEXITCODE)" }
    Write-Host "TAS deployed: $destination"
}

function Install-EtniesStartupResource {
    param(
        [Parameter(Mandatory)][string]$ServerRoot,
        [Parameter(Mandatory)][string]$MapName
    )

    $resources = Join-Path $ServerRoot 'mods\deathmatch\resources'
    $startupRoot = Join-Path $resources 'etnies-startup'
    New-Item -ItemType Directory -Path $startupRoot -Force | Out-Null

    $meta = @'
<meta>
    <info author='local' name='Etnies test startup' type='script' />
    <script src='server.lua' type='server' />
</meta>
'@
    Set-Content -LiteralPath (Join-Path $startupRoot 'meta.xml') -Value $meta -Encoding UTF8

    # The configured map name is local/trusted. Escape a possible apostrophe so
    # it can be embedded safely in the generated Lua single-quoted string.
    $escapedMapName = $MapName.Replace("'", "\'")
    $serverLua = @"
local targetMapName = '$escapedMapName'
local attempts = 0

local function startEtnies()
    attempts = attempts + 1

    local manager = getResourceFromName('mapmanager')
    local race = getResourceFromName('race')
    local targetMap = getResourceFromName(targetMapName)

    if not manager or not race or not targetMap then
        outputDebugString('[etnies-startup] waiting for mapmanager/race/' .. targetMapName, 2)
    elseif getResourceState(manager) ~= 'running' then
        outputDebugString('[etnies-startup] waiting for mapmanager to start', 2)
    else
        local ok, changed = pcall(function()
            return exports.mapmanager:changeGamemode(race, targetMap)
        end)
        if ok and changed then
            outputDebugString('[etnies-startup] Race started with ' .. targetMapName)
            return
        end
        outputDebugString('[etnies-startup] mapmanager changeGamemode did not succeed yet', 2)
    end

    if attempts < 30 then
        setTimer(startEtnies, 500, 1)
    else
        outputDebugString('[etnies-startup] failed to start Race + ' .. targetMapName, 1)
    end
end

addEventHandler('onResourceStart', resourceRoot, function()
    setTimer(startEtnies, 500, 1)
end)
"@
    Set-Content -LiteralPath (Join-Path $startupRoot 'server.lua') -Value $serverLua -Encoding UTF8
    Write-Host "Installed startup resource: $startupRoot"
}

$liveConfigPath = Join-Path $LiveServerRoot 'mods\deathmatch\mtaserver.conf'
$debugConfigPath = Join-Path $DebugServerRoot 'mods\deathmatch\mtaserver.conf'

# Keep the ordinary server and mtasa-blue/native-capture server on the same
# cadence as the 100 FPS Etnies source recording.
$live = Load-ServerConfig -Path $liveConfigPath
Set-FpsLimit -Document $live -Value $FpsLimit
Ensure-StartupResource -Document $live -Name 'play' -Startup:$false
Ensure-StartupResource -Document $live -Name 'mapmanager' -Startup:$true
Ensure-StartupResource -Document $live -Name 'race' -Startup:$true
Ensure-StartupResource -Document $live -Name 'tas' -Startup:$true
Ensure-StartupResource -Document $live -Name 'etnies-startup' -Startup:$true
Save-ServerConfig -Document $live -Path $liveConfigPath

$debug = Load-ServerConfig -Path $debugConfigPath
Set-FpsLimit -Document $debug -Value $FpsLimit
Save-ServerConfig -Document $debug -Path $debugConfigPath

# Use the same TAS code in both server trees. The native harness may prepare
# its TAS folder again from this repository later; that preserves equivalence.
Mirror-TasResource -ServerRoot $LiveServerRoot
Mirror-TasResource -ServerRoot $DebugServerRoot
Install-EtniesStartupResource -ServerRoot $LiveServerRoot -MapName $MapResource

$liveMapPath = Join-Path (Join-Path $LiveServerRoot 'mods\deathmatch\resources') $MapResource
if (-not (Test-Path -LiteralPath $liveMapPath)) {
    Write-Warning "The requested Etnies resource was not found at $liveMapPath. Startup is configured, but the map cannot be selected until that resource exists."
}

Write-Host ''
Write-Host "Done. Both server configs use fpslimit=$FpsLimit."
Write-Host 'The normal server has play disabled and starts mapmanager, race, tas, and etnies-startup.'
Write-Host 'TAS showPlaybackFrameHud defaults to true; use /tascvar showPlaybackFrameHud false to hide it.'
