param(
    [string]$Repository = "$env:USERPROFILE\forex-bot"
)

$ErrorActionPreference = "Stop"
$taskName = "AAQTS-AI-Research"
$currentUser = "$env:USERDOMAIN\$env:USERNAME"
$script = Join-Path $Repository "scripts\windows\start-ai-research-watcher.ps1"

if (-not (Test-Path -LiteralPath $script)) {
    throw "AAQTS AI research watcher launcher was not found: $script"
}

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal `
    -UserId $currentUser `
    -LogonType Interactive `
    -RunLevel Highest
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $currentUser
$trigger.Delay = "PT60S"
$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$script`""

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Force | Out-Null

Start-ScheduledTask -TaskName $taskName
Start-Sleep -Seconds 3
Get-ScheduledTask -TaskName $taskName | Select-Object TaskName, State
