param(
    [Parameter(Mandatory = $true)][string]$Installer,
    [string]$SandboxRoot = (Join-Path $env:RUNNER_TEMP 'deilaw-phase3-nsis-smoke')
)
$ErrorActionPreference = 'Stop'
$Installer = (Resolve-Path -LiteralPath $Installer).Path
$SandboxRoot = [System.IO.Path]::GetFullPath($SandboxRoot)
$InstallDir = Join-Path $SandboxRoot 'install'
$Settings = Join-Path $InstallDir 'data\settings.json'
$Sentinel = Join-Path $InstallDir 'data\phase3_keep_my_data.txt'
# Refuse an existing path so test cleanup cannot affect anyone's real files.
if (Test-Path -LiteralPath $SandboxRoot) { throw 'Smoke-test sandbox already exists; refusing to overwrite it' }
New-Item -ItemType Directory -Path $SandboxRoot | Out-Null

function Invoke-Installer {
    # A GUI-subsystem EXE may run asynchronously under PowerShell's call operator,
    # leaving LASTEXITCODE unset. Start-Process -Wait observes its actual exit.
    $run = Start-Process -FilePath $Installer -ArgumentList @('/S', "/D=$InstallDir") -Wait -PassThru
    if ($run.ExitCode -ne 0) { throw "NSIS install failed: $($run.ExitCode)" }
}
try {
    # Silent mode tests default-deny preferences. Privacy GUI still requires
    # interactive inspection on a real Windows desktop before release.
    Invoke-Installer
    if (-not (Test-Path -LiteralPath (Join-Path $InstallDir 'DeiLaw.exe'))) { throw 'Installed EXE missing' }
    if (-not (Test-Path -LiteralPath $Settings)) { throw 'Installed settings missing' }
    $prefs = Get-Content -LiteralPath $Settings -Raw | ConvertFrom-Json
    foreach ($key in @('auto_check_program_updates','auto_update_laws_on_startup','background_reply_notifications')) {
        if ($prefs.$key -ne $false) { throw "Unexpected default network opt-in: $key" }
    }
    if (-not (Test-Path -LiteralPath (Join-Path $InstallDir 'THIRD_PARTY_LICENSES\license_manifest.json'))) {
        throw 'Third-party license manifest missing after install'
    }
    'retain user data' | Set-Content -LiteralPath $Sentinel -Encoding UTF8
    @{ auto_check_program_updates = $true; auto_update_laws_on_startup = $true; background_reply_notifications = $true } |
        ConvertTo-Json -Compress | Set-Content -LiteralPath $Settings -Encoding UTF8
    Invoke-Installer
    $saved = Get-Content -LiteralPath $Settings -Raw | ConvertFrom-Json
    if ($saved.auto_check_program_updates -ne $true) { throw 'Reinstall overwrote existing preferences' }
    if ((Get-Content -LiteralPath $Sentinel -Raw).Trim() -ne 'retain user data') {
        throw 'Reinstall modified user data'
    }
    $Uninstaller = Join-Path $InstallDir 'Uninstall.exe'
    if (-not (Test-Path -LiteralPath $Uninstaller)) { throw 'Uninstaller missing' }
    $removed = Start-Process -FilePath $Uninstaller -ArgumentList '/S' -Wait -PassThru
    if ($removed.ExitCode -ne 0) { throw "NSIS uninstall failed: $($removed.ExitCode)" }
    if (Test-Path (Join-Path $InstallDir 'DeiLaw.exe')) { throw 'Application EXE not removed' }
    if (Test-Path (Join-Path $InstallDir 'THIRD_PARTY_LICENSES')) { throw 'Third-party license folder not removed' }
    if (-not (Test-Path -LiteralPath $Sentinel)) { throw 'Uninstall deleted user data' }
    if (-not (Test-Path -LiteralPath $Settings)) { throw 'Uninstall deleted user preferences' }
    Write-Host 'NSIS smoke OK: install, default privacy, reinstall and data-preserving uninstall'
}
finally {
    if (Test-Path -LiteralPath $SandboxRoot) { Remove-Item -LiteralPath $SandboxRoot -Force -Recurse }
}
