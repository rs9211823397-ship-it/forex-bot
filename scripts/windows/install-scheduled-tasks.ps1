param(
    [string]$Repository = "$env:USERPROFILE\forex-bot"
)

$ErrorActionPreference = "Stop"
$currentUser = "$env:USERDOMAIN\$env:USERNAME"
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId $currentUser -LogonType Interactive -RunLevel Highest

function Register-AAQTSTask([string]$Name, [string]$Script, [int]$DelaySeconds) {
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $currentUser
    $trigger.Delay = "PT${DelaySeconds}S"
    $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$Script`""
    Register-ScheduledTask -TaskName $Name -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
}

Register-AAQTSTask "AAQTS-MT5" (Join-Path $Repository "scripts\windows\start-mt5.ps1") 10
Register-AAQTSTask "AAQTS-Demo-Engine" (Join-Path $Repository "scripts\windows\start-demo-engine.ps1") 40
Register-AAQTSTask "AAQTS-Telegram" (Join-Path $Repository "scripts\windows\start-telegram.ps1") 50

Get-ScheduledTask -TaskName "AAQTS-MT5", "AAQTS-Demo-Engine", "AAQTS-Telegram" | Select-Object TaskName, State
