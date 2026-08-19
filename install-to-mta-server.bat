@echo off
setlocal EnableExtensions DisableDelayedExpansion

set "REPO_DIR=%~dp0"
set "SOURCE=%REPO_DIR%new\tas"
set "MTA_RESOURCES=C:\Program Files (x86)\MTA San Andreas 1.6\server\mods\deathmatch\resources"
set "DESTINATION=%MTA_RESOURCES%\tas"
set "STATUS=1"

echo.
echo TAS resource installer
echo ======================
echo Source:      "%SOURCE%"
echo Destination: "%DESTINATION%"
echo.

if not exist "%SOURCE%\." (
    echo ERROR: The source directory was not found.
    echo        Check that this script is in the repository root.
    goto :finish
)

echo Mirroring source into destination...
echo Only the destination tas resource is changed.
echo.

robocopy "%SOURCE%" "%DESTINATION%" /MIR /R:2 /W:2
set "ROBOCOPY_STATUS=%ERRORLEVEL%"

if %ROBOCOPY_STATUS% GEQ 8 (
    echo.
    echo ERROR: The TAS resource could not be copied completely.
    echo        robocopy exit code: %ROBOCOPY_STATUS%
    echo        If this is a permissions error, run this script as Administrator.
    goto :finish
)

set "STATUS=0"
echo.
echo The TAS resource was updated successfully.
echo        robocopy exit code: %ROBOCOPY_STATUS%

goto :finish

:finish
echo.
if "%STATUS%"=="0" (
    echo SUCCESS: Deployment finished.
) else (
    echo FAILURE: Deployment did not finish successfully.
)
echo.
echo Press any key to close this window.
pause >nul

endlocal & exit /b %STATUS%
