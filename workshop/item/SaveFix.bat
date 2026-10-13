@echo off
rem ===========================================================================
rem  SaveFix - Beyond 65535
rem
rem  Launcher for SaveFix.ps1. The PowerShell script does the actual work; this
rem  batch file exists so the tool can be started by double-clicking.
rem
rem  Usage:  SaveFix.bat                    report only
rem          SaveFix.bat Apply              patch to 4 MiB
rem          SaveFix.bat Apply -MiB 8       patch to 8 MiB
rem          SaveFix.bat Restore            put the original back
rem
rem  Exit codes from SaveFix.ps1:  0 ok, 1 error, 2 refused to act,
rem                                3 write failed, 4 access denied.
rem
rem  ---------------------------------------------------------------------------
rem  WHY THIS FILE USES LABELS INSTEAD OF "if ( ... )" BLOCKS
rem
rem  cmd.exe parses a whole parenthesised block before executing any of it.
rem  Steam normally lives under "C:\Program Files (x86)", so %~dp0 contains a
rem  closing parenthesis - and one of those inside a block tears the block
rem  apart. cmd then prints "....\SaveFix.ps1 was unexpected at this time." and
rem  does nothing at all, even when the branch would never have been taken.
rem
rem  Every branch below is therefore a label + goto. Please keep it that way.
rem  ---------------------------------------------------------------------------

setlocal EnableExtensions

set "HERE=%~dp0"
set "PS1=%HERE%SaveFix.ps1"

if not exist "%PS1%" goto :no_ps1

rem ---- Run the tool. Nothing is pre-emptively elevated: the game folder is
rem ---- often writable as-is (Steam grants it), and asking for administrator
rem ---- rights when they are not needed is just noise.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%PS1%" %*
set "RC=%ERRORLEVEL%"

if "%RC%"=="4" goto :denied
goto :report

:denied
echo.
echo   The tool needs administrator rights to change that file.
echo.
set "ANS="
set /p "ANS=  Run it again with administrator rights now? [y/N] "
if /i "%ANS%"=="y" goto :elevate
goto :report

:elevate
echo.
echo   A Windows UAC prompt will appear - choose "Yes".
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -ArgumentList '%*' -Verb RunAs"
if errorlevel 1 goto :elev_fail
echo.
echo   The elevated window runs the tool and keeps its own result on screen.
echo.
pause
exit /b 0

:elev_fail
echo.
echo   Could not start an elevated window automatically.
echo   Right-click SaveFix.bat and choose "Run as administrator" instead.
echo.
pause
exit /b 1

:report
echo.
if "%RC%"=="1" echo   (exit code 1 - something went wrong, see the message above)
if "%RC%"=="2" echo   (exit code 2 - nothing was changed, see the message above)
if "%RC%"=="3" echo   (exit code 3 - the write failed, see the message above)
if "%RC%"=="4" echo   (exit code 4 - administrator rights are required)
if "%RC%"=="0" echo   (finished - nothing else to do)
pause
exit /b %RC%

:no_ps1
echo.
echo   ERROR: SaveFix.ps1 was not found next to this file.
echo          Expected: %PS1%
echo.
echo   Keep both files together, in the folder Steam downloaded them to.
echo.
pause
exit /b 1
