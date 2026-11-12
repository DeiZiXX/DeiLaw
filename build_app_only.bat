@echo off
setlocal EnableExtensions
cd /d "%~dp0"

rem Build directly from cmd.exe: no PowerShell execution-policy changes needed.
set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
set "PYTHON_SWITCH="
if exist "%PYTHON_EXE%" goto python_ready

where py >nul 2>&1
if not errorlevel 1 (
    set "PYTHON_EXE=py"
    set "PYTHON_SWITCH=-3"
    goto python_ready
)

where python >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python 3 is not installed or not in PATH.
    echo Install Python 3.11 or newer and try again.
    goto failed
)
set "PYTHON_EXE=python"

:python_ready
echo Checking Python...
"%PYTHON_EXE%" %PYTHON_SWITCH% --version
if errorlevel 1 goto failed

echo Installing pinned DeiLaw dependencies...
"%PYTHON_EXE%" %PYTHON_SWITCH% -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto failed
"%PYTHON_EXE%" %PYTHON_SWITCH% -m pip install --disable-pip-version-check -r requirements-build.txt
if errorlevel 1 goto failed

echo Verifying source files...
"%PYTHON_EXE%" %PYTHON_SWITCH% scripts\verify_source.py
if errorlevel 1 goto failed

echo Running security and binder tests...
"%PYTHON_EXE%" %PYTHON_SWITCH% -m unittest discover -s tests -q
if errorlevel 1 goto failed

echo Building DeiLaw.exe for Windows...
"%PYTHON_EXE%" %PYTHON_SWITCH% -m PyInstaller --noconfirm --clean --onedir --windowed --name DeiLaw --icon "installer\assets\deilaw_installer.ico" --add-data "assets;assets" main.py
if errorlevel 1 goto failed

if not exist "dist\DeiLaw\DeiLaw.exe" (
    echo ERROR: The expected output executable was not created.
    goto failed
)
echo.
echo SUCCESS: dist\DeiLaw\DeiLaw.exe
echo This is an UNSIGNED development build, not a public release.
pause
exit /b 0

:failed
echo.
echo BUILD FAILED. Send the error shown above to the DeiLaw developer.
pause
exit /b 1
