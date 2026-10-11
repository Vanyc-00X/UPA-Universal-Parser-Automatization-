<#
.SYNOPSIS
    Устанавливает Playwright Chromium с зеркалами и проверкой Chrome/Edge.

.EXAMPLE
    .\scripts\install-chromium.ps1
    .\scripts\install-chromium.ps1 -Force
#>

[CmdletBinding()]
param(
    [switch]$Force,
    [string]$Python
)

$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $PSScriptRoot
if (-not $Python) {
    $venvPython = Join-Path $RepoRoot '.venv\Scripts\python.exe'
    if (Test-Path $venvPython) { $Python = $venvPython }
    else { $Python = (Get-Command python -ErrorAction Stop).Source }
}

$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $RepoRoot 'data\_pw-browsers'
New-Item -ItemType Directory -Force -Path $env:PLAYWRIGHT_BROWSERS_PATH | Out-Null

$args = @((Join-Path $RepoRoot 'scripts\install_chromium.py'), '--python', $Python)
if ($Force) { $args += '--force' }

& $Python @args
exit $LASTEXITCODE
