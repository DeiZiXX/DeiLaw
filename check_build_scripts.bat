@echo off
cd /d "%~dp0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0check_build_scripts.ps1"
set "DEILAW_EXIT=%ERRORLEVEL%"
echo.
pause
exit /b %DEILAW_EXIT%
