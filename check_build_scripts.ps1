$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

$files = @(
    (Join-Path $PSScriptRoot 'build_release.ps1'),
    (Join-Path $PSScriptRoot 'publish_release.ps1')
)

$failed = $false

foreach ($file in $files) {
    $tokens = $null
    $errors = $null

    [System.Management.Automation.Language.Parser]::ParseFile(
        $file,
        [ref]$tokens,
        [ref]$errors
    ) | Out-Null

    if ($errors.Count -gt 0) {
        $failed = $true
        Write-Host ""
        Write-Host "SYNTAX ERROR: $file" -ForegroundColor Red

        foreach ($errorItem in $errors) {
            Write-Host $errorItem.Message -ForegroundColor Red
            Write-Host (
                "Line {0}, column {1}" -f
                $errorItem.Extent.StartLineNumber,
                $errorItem.Extent.StartColumnNumber
            ) -ForegroundColor Yellow
        }
    }
    else {
        Write-Host "OK: $file" -ForegroundColor Green
    }
}

if ($failed) {
    exit 1
}

Write-Host ''
Write-Host 'PowerShell syntax check passed.' -ForegroundColor Green
exit 0
