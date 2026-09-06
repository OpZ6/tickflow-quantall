[CmdletBinding()]
param(
    [ValidatePattern('^([01]\d|2[0-3]):[0-5]\d$')]
    [string]$At = '18:30',
    [int]$BackendPort = 3018,
    [string]$TaskName = 'TickFlow-Quantall-UpdateAll'
)

$ErrorActionPreference = 'Stop'
$UpdateScript = Join-Path $PSScriptRoot 'update_all.ps1'
if (-not (Test-Path -LiteralPath $UpdateScript)) {
    throw "Update script not found: $UpdateScript"
}

$powerShell = (Get-Command powershell.exe).Source
$arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$UpdateScript`" -BackendPort $BackendPort"
$action = New-ScheduledTaskAction -Execute $powerShell -Argument $arguments
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday -At $At
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Description 'Check TickFlow data freshness and run the full pipeline when stale.' -Force | Out-Null

Write-Host "Scheduled task installed: $TaskName (weekdays at $At; starts when available)." -ForegroundColor Green
Write-Host "Remove with: Unregister-ScheduledTask -TaskName '$TaskName' -Confirm:`$false"
