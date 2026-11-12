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

$IconFile = Join-Path $PSScriptRoot 'installer\assets\deilaw_installer.ico'
$VersionFile = Join-Path $PSScriptRoot 'installer\version_info.txt'
$AssetsDir = Join-Path $PSScriptRoot 'assets'
$MainFile = Join-Path $PSScriptRoot 'main.py'
$SpecFolder = Join-Path $PSScriptRoot 'build\generated-spec'
if (!(Test-Path -LiteralPath $IconFile -PathType Leaf)) { throw "Installer icon missing: $IconFile. Restore installer/assets from the full source archive." }
if (!(Test-Path -LiteralPath $VersionFile -PathType Leaf)) { throw "Windows version metadata missing: $VersionFile" }
if (!(Test-Path -LiteralPath $AssetsDir -PathType Container)) { throw "Assets folder missing: $AssetsDir" }
New-Item -ItemType Directory -Path $SpecFolder -Force | Out-Null
& $Python -m PyInstaller --noconfirm --clean --onedir --windowed --name DeiLaw --specpath $SpecFolder --version-file $VersionFile --icon $IconFile --add-data "$AssetsDir;assets" $MainFile
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed.' }

$Exe = Join-Path $PSScriptRoot 'dist\DeiLaw\DeiLaw.exe'
if (!(Test-Path -LiteralPath $Exe)) { throw 'Missing DeiLaw.exe in dist.' }
Write-Host "Windows program built: $Exe" -ForegroundColor Green
