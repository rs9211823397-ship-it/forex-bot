$ErrorActionPreference = "Stop"
$repo = Join-Path $env:USERPROFILE "forex-bot"
$python = Join-Path $repo ".venv\Scripts\python.exe"
$terminal = "C:\Program Files\Exness JO MT5 Terminal\terminal64.exe"
$status = Join-Path $repo "runtime\aaqts_status_exness_demo.json"
$output = Join-Path $repo "outputs\validation"
$before = Join-Path $output "restart_before.json"
$after = Join-Path $output "restart_after.json"

Set-Location $repo
& $python scripts\capture_restart_state.py --terminal $terminal --status $status --output $before
$oldHeartbeat = (Get-Content $status -Raw | ConvertFrom-Json).heartbeat_utc

Stop-ScheduledTask -TaskName "AAQTS-Demo-Engine"
$deadline = (Get-Date).AddSeconds(60)
do {
    Start-Sleep -Seconds 2
    $workers = Get-CimInstance Win32_Process | Where-Object {
        $_.Name -eq "python.exe" -and $_.CommandLine -match "main.py"
    }
} while ($workers -and (Get-Date) -lt $deadline)
if ($workers) { throw "AAQTS worker did not stop cleanly; no process was force-killed" }

Start-ScheduledTask -TaskName "AAQTS-Demo-Engine"
$deadline = (Get-Date).AddMinutes(3)
do {
    Start-Sleep -Seconds 5
    $runtime = Get-Content $status -Raw | ConvertFrom-Json
    $ready = $runtime.status -eq "RUNNING" -and $runtime.heartbeat_utc -ne $oldHeartbeat
} while (-not $ready -and (Get-Date) -lt $deadline)
if (-not $ready) { throw "Restarted worker did not produce a fresh RUNNING heartbeat" }

& $python scripts\capture_restart_state.py --terminal $terminal --status $status --output $after
& $python scripts\restart_soak_report.py --before $before --after $after
