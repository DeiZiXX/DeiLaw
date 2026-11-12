param(
    [string]$NsisCompiler = 'makensis.exe',
    [string]$SignTool = 'signtool.exe',
    [string]$CertificateThumbprint = $env:DEILAW_AUTHENTICODE_THUMBPRINT,
    [string]$Ed25519Key = $env:DEILAW_UPDATE_SIGNING_KEY
)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$Python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (!(Test-Path -LiteralPath $Python)) { $Python = 'python' }

if ([string]::IsNullOrWhiteSpace($CertificateThumbprint)) {
    throw 'Release blocked: set DEILAW_AUTHENTICODE_THUMBPRINT of a valid code-signing certificate.'
}
if ([string]::IsNullOrWhiteSpace($Ed25519Key) -or !(Test-Path -LiteralPath $Ed25519Key)) {
    throw 'Release blocked: set DEILAW_UPDATE_SIGNING_KEY to an offline private key outside the repository.'
}
& $Python -c 'import update_trust; assert len(update_trust.UPDATE_ED25519_PUBLIC_KEY_B64) > 30, "Release signing public key is not pinned"'
if ($LASTEXITCODE -ne 0) { throw 'Release blocked: pin signing public key in update_trust.py.' }

& (Join-Path $PSScriptRoot 'build_app_only.ps1')
if ($LASTEXITCODE -ne 0) { throw 'Application build failed.' }

$Version = (& $Python -c 'from app_version import APP_VERSION; print(APP_VERSION)').Trim()
$AppExe = Join-Path $PSScriptRoot 'dist\DeiLaw\DeiLaw.exe'
if (!(Test-Path -LiteralPath $AppExe)) { throw 'DeiLaw.exe missing after build.' }

# The installed application itself must be Authenticode-signed, not only its installer.
& $SignTool sign /sha1 $CertificateThumbprint /fd SHA256 /tr https://timestamp.digicert.com /td SHA256 $AppExe
if ($LASTEXITCODE -ne 0) { throw 'Authenticode signing of DeiLaw.exe failed.' }
& $SignTool verify /pa /v $AppExe
if ($LASTEXITCODE -ne 0) { throw 'Windows trust verification failed for DeiLaw.exe.' }
$AppSignature = Get-AuthenticodeSignature -LiteralPath $AppExe
if ($AppSignature.Status -ne 'Valid') { throw 'DeiLaw.exe has no valid Authenticode signature.' }

& $NsisCompiler "/DAPP_VERSION=$Version" "/DDEILAW_SOURCE=$PSScriptRoot\dist\DeiLaw" "/DDEILAW_OUTPUT=$PSScriptRoot\release" 'installer\DeiLaw.nsi'
if ($LASTEXITCODE -ne 0) { throw 'NSIS compilation failed.' }
$Installer = Join-Path $PSScriptRoot "release\DeiLaw_Setup_v$Version.exe"
if (!(Test-Path -LiteralPath $Installer)) { throw 'Release installer missing.' }

& $SignTool sign /sha1 $CertificateThumbprint /fd SHA256 /tr https://timestamp.digicert.com /td SHA256 $Installer
if ($LASTEXITCODE -ne 0) { throw 'Authenticode signing failed.' }
$Signature = Get-AuthenticodeSignature -LiteralPath $Installer
if ($Signature.Status -ne 'Valid') { throw 'Authenticode signature verification failed.' }
& $SignTool verify /pa /v $Installer
if ($LASTEXITCODE -ne 0) { throw 'Windows trust verification failed for installer.' }

$Manifest = Join-Path $PSScriptRoot 'release\update_manifest.json'
& $Python scripts/create_update_manifest.py $Version $Installer $Manifest
if ($LASTEXITCODE -ne 0) { throw 'Manifest creation failed.' }
& $Python scripts/sign_update_manifest.py $Ed25519Key $Manifest
if ($LASTEXITCODE -ne 0) { throw 'Manifest signing failed.' }
& $Python -c 'import json,sys,update_trust; update_trust.verify_manifest(json.load(open(sys.argv[1],encoding="utf-8")));print("Signed manifest verified")' $Manifest
if ($LASTEXITCODE -ne 0) { throw 'Release manifest verification failed.' }
Write-Host "Locally signed NSIS release ready at $Installer" -ForegroundColor Green
