param(
    [string]$BotRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$CcDataDir = (Join-Path $env:USERPROFILE ".cc-connect")
)

$ErrorActionPreference = "Stop"

$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew

# Watchdog: every 5 minutes, run the hidden launcher. The launcher checks
# whether cc-connect is already running and exits if so.
$watchAction = New-ScheduledTaskAction `
    -Execute "C:\Windows\System32\wscript.exe" `
    -Argument ('"' + (Join-Path $CcDataDir "start_cc_hidden.vbs") + '"')
$watchTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 5)
Register-ScheduledTask `
    -TaskName "cc-connect-watchdog" `
    -Action $watchAction `
    -Trigger $watchTrigger `
    -Settings $settings `
    -Principal $principal `
    -Force | Out-Null

# Daily backup at 04:17 (after the 03:17 memory consolidation).
$backupAction = New-ScheduledTaskAction `
    -Execute "C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe" `
    -Argument ('-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + (Join-Path $BotRoot "tools\backup.ps1") + '"')
$backupTrigger = New-ScheduledTaskTrigger -Daily -At 04:17
Register-ScheduledTask `
    -TaskName "cc-connect-backup" `
    -Action $backupAction `
    -Trigger $backupTrigger `
    -Settings $settings `
    -Principal $principal `
    -Force | Out-Null

Get-ScheduledTask -TaskName "cc-connect-watchdog", "cc-connect-backup" |
    Select-Object TaskName, State
Get-ScheduledTaskInfo -TaskName "cc-connect-watchdog" |
    Select-Object TaskName, NextRunTime, LastRunTime, LastTaskResult
