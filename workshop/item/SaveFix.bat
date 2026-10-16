@echo off
rem ===========================================================================
rem  SaveFix - Beyond 65535
rem
rem  Launcher for SaveFix.ps1. The PowerShell script does the actual work; this
rem  batch file exists so the tool can be started by double-clicking.
rem
rem  Usage:  SaveFix.bat                    report, then offer to patch
rem          SaveFix.bat Apply              patch to 4 MiB
rem          SaveFix.bat Apply -MiB 8       patch to 8 MiB
rem          SaveFix.bat Restore            put the original back
rem
rem  Exit codes from SaveFix.ps1:  0 ok, 1 error, 2 refused to act,
rem                                3 write failed, 4 access denied,
rem                                10 report finished - the executable is unpatched.
rem
rem  ---------------------------------------------------------------------------
rem  WHY A DOUBLE-CLICK RUN NOW ENDS WITH A QUESTION
rem
rem  The report used to end by telling the reader to run "SaveFix.bat Apply".
rem  That is no help to somebody who got there by double-clicking: it gives them
rem  no console window to type a command into, and double-clicking SaveFix.ps1
rem  itself just opens Notepad.  So when no argument is passed at all, this
rem  launcher runs the report and then offers to do the patch itself.
rem
rem  Passing any argument skips the question entirely, so scripted use and every
rem  documented command behave exactly as before.
rem
rem  Exit code 10 carries the "report ran, there is something to do" signal.  It
rem  is not an error: nothing went wrong and nothing was changed.  A status run
rem  against an already-patched executable still exits 0.
rem  ---------------------------------------------------------------------------
rem
rem  ---------------------------------------------------------------------------
rem  WHY THIS FILE USES LABELS INSTEAD OF "if ( ... )" BLOCKS
rem
rem  cmd.exe parses a whole parenthesised block before executing any of it.
rem  Steam normally lives under "C:\Program Files (x86)", so %~dp0 contains a
rem  closing parenthesis - and one of those inside a block tears the block
rem  apart.  cmd then prints "....\SaveFix.ps1 was unexpected at this time." and
rem  does nothing at all, even when the branch would never have been taken.
rem
rem  Every branch below is therefore a label + goto.  Please keep it that way.
rem  ---------------------------------------------------------------------------

setlocal EnableExtensions

set "HERE=%~dp0"
set "PS1=%HERE%SaveFix.ps1"

if not exist "%PS1%" goto :no_ps1

rem ---- Any argument at all means the caller already knows what they want.
if not "%~1"=="" goto :have_args

rem ---- No argument: somebody double-clicked this file.  Report first.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%PS1%" Status
set "RC=%ERRORLEVEL%"
if "%RC%"=="4" goto :denied_status
if "%RC%"=="10" goto :offer
goto :report

:offer
echo.
echo   The original 65,536-byte limit is still in place.
echo.
set "ANS="
set /p "ANS=  Raise it to 4 MiB now? [y/N] "
if /i not "%ANS%"=="y" goto :report
echo.
rem ---- -Yes because the question has just been asked and answered right here.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%PS1%" Apply -Yes
set "RC=%ERRORLEVEL%"
if "%RC%"=="4" goto :denied_apply
goto :report

:have_args
rem ---- Run the tool.  Nothing is pre-emptively elevated: the game folder is
rem ---- often writable as-is (Steam grants it), and asking for administrator
rem ---- rights when they are not needed is just noise.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%PS1%" %*
set "RC=%ERRORLEVEL%"
if "%RC%"=="4" goto :denied_args
goto :report

rem ---- Access denied.  Each entry point re-runs THE SAME thing elevated, so an
rem ---- elevated retry can never do more than the user originally asked for.

:denied_status
echo.
echo   Administrator rights are needed even to read that file.
echo.
set "ANS="
set /p "ANS=  Run it again with administrator rights now? [y/N] "
if /i "%ANS%"=="y" goto :elev_status
goto :report

:denied_apply
echo.
echo   Administrator rights are needed to change that file.
echo.
set "ANS="
set /p "ANS=  Run it again with administrator rights now? [y/N] "
if /i "%ANS%"=="y" goto :elev_apply
goto :report

:denied_args
echo.
echo   Administrator rights are needed to change that file.
echo.
set "ANS="
set /p "ANS=  Run it again with administrator rights now? [y/N] "
if /i "%ANS%"=="y" goto :elev_args
goto :report

:elev_status
echo.
echo   A Windows UAC prompt will appear - choose "Yes".
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
if errorlevel 1 goto :elev_fail
goto :elev_done

:elev_apply
echo.
echo   A Windows UAC prompt will appear - choose "Yes".
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -ArgumentList 'Apply -Yes' -Verb RunAs"
if errorlevel 1 goto :elev_fail
goto :elev_done

:elev_args
echo.
echo   A Windows UAC prompt will appear - choose "Yes".
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -ArgumentList '%*' -Verb RunAs"
if errorlevel 1 goto :elev_fail
goto :elev_done

:elev_done
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
if "%RC%"=="10" echo   (exit code 10 - nothing was changed)
if "%RC%"=="0" echo   (finished)
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
