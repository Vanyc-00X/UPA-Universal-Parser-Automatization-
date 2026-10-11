<#
.SYNOPSIS
    Создаёт ярлык UPA на рабочем столе (запуск через launch.cmd).
#>
[CmdletBinding()]
param(
    [string]$Name = 'UPA'
)

$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $PSScriptRoot
$Target = Join-Path $RepoRoot 'launch.cmd'
$Desktop = [Environment]::GetFolderPath('Desktop')
$ShortcutPath = Join-Path $Desktop "$Name.lnk"

if (-not (Test-Path $Target)) {
    throw "Не найден $Target"
}

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($ShortcutPath)
$shortcut.TargetPath = $Target
$shortcut.WorkingDirectory = $RepoRoot
$shortcut.WindowStyle = 1
$shortcut.Description = 'Universal Parser Automatization'
$shortcut.Save()

Write-Host "Ярлык создан: $ShortcutPath" -ForegroundColor Green
