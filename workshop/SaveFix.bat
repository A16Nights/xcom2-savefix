@echo off
rem ===========================================================================
rem  SaveFix - Beyond 65535
rem
rem  Launcher for SaveFix.ps1. The PowerShell script does the actual work; this
rem  batch file only exists so the tool can be started by double-clicking, and
rem  so the execution policy does not have to be changed system-wide.
rem
rem  Usage:  SaveFix.bat                    report only
rem          SaveFix.bat Apply              patch to 4 MiB
rem          SaveFix.bat Apply -MiB 8       patch to 8 MiB
rem          SaveFix.bat Restore            put the original back
rem ===========================================================================

setlocal
set "HERE=%~dp0"
set "PS1=%HERE%SaveFix.ps1"

if not exist "%PS1%" (
    echo.
    echo   ERROR: SaveFix.ps1 was not found next to this file.
    echo          Expected: %PS1%
    echo.
    echo   Keep the files together in the folder Steam downloaded.
    echo.
    pause
    exit /b 1
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%PS1%" %*
set "RC=%ERRORLEVEL%"

echo.
if "%RC%"=="1" echo   (exit code 1 - something went wrong, see the message above)
if "%RC%"=="2" echo   (exit code 2 - refused to act, nothing was changed)
if "%RC%"=="3" echo   (exit code 3 - a write failed, see the message above)

pause
exit /b %RC%
