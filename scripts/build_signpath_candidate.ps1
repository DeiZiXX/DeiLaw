param(
    [string]$NsisCompiler = "makensis.exe",
    [switch]$SkipAppBuild
)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Join-Path $PSScriptRoot '..')
$Root = (Get-Location).Path
$Python = Join-Path $Root '.venv\Scripts\python.exe'
if (!(Test-Path -LiteralPath $Python)) { $Python = 'python' }
$Version = (& $Python -c 'from app_version import APP_VERSION; print(APP_VERSION)').Trim()
if ($LASTEXITCODE -ne 0 -or $Version -notmatch '^\d+\.\d+\.\d+$') { throw 'Invalid stable version.' }
if (-not $SkipAppBuild) {
    & (Join-Path $Root 'build_app_only.ps1')
    if ($LASTEXITCODE -ne 0) { throw 'Application build failed.' }
}
$Exe = Join-Path $Root 'dist\DeiLaw\DeiLaw.exe'
if (!(Test-Path -LiteralPath $Exe)) { throw 'DeiLaw.exe was not built.' }
$Release = Join-Path $Root 'release'
New-Item -ItemType Directory -Force -Path $Release | Out-Null
# This builds an UNSIGNED candidate. Only SignPath can sign after project acceptance.
& $NsisCompiler "/V2" "/DAPP_VERSION=$Version" "/DDEILAW_SOURCE=$Root\dist\DeiLaw" "/DDEILAW_OUTPUT=$Release" (Join-Path $Root 'installer\DeiLaw.nsi')
if ($LASTEXITCODE -ne 0) { throw 'NSIS compilation failed.' }
$Setup = Join-Path $Release "DeiLaw_Setup_v$Version.exe"
if (!(Test-Path -LiteralPath $Setup)) { throw "Installer missing: $Setup" }
& $Python scripts\build_inventory.py dist\DeiLaw release\build_inventory.json
if ($LASTEXITCODE -ne 0) { throw 'Inventory failed.' }
Write-Host "UNSIGNED candidate: $Setup" -ForegroundColor Yellow
Write-Host 'Do not publish it as signed or approved by SignPath.'
