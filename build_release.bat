@echo off
setlocal
powershell.exe -NoProfile -File "%~dp0build_release.ps1"
exit /b %ERRORLEVEL%
