$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

$Python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (!(Test-Path -LiteralPath $Python)) { $Python = 'python' }

& $Python -m pip install --disable-pip-version-check -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Cannot install runtime requirements.' }
& $Python -m pip install --disable-pip-version-check -r requirements-build.txt
if ($LASTEXITCODE -ne 0) { throw 'Cannot install pinned build requirements.' }

& $Python scripts/verify_source.py
if ($LASTEXITCODE -ne 0) { throw 'Source verification failed.' }
& $Python -m unittest discover -s tests -q
if ($LASTEXITCODE -ne 0) { throw 'Security or binder tests failed.' }

& $Python -m PyInstaller --noconfirm --clean --onedir --windowed --name DeiLaw --icon 'installer\assets\deilaw_installer.ico' --add-data 'assets;assets' main.py
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed.' }

$Exe = Join-Path $PSScriptRoot 'dist\DeiLaw\DeiLaw.exe'
if (!(Test-Path -LiteralPath $Exe)) { throw 'Missing DeiLaw.exe in dist.' }
Write-Host "Windows program built: $Exe" -ForegroundColor Green
