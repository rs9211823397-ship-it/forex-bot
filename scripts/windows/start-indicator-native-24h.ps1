param(
    [string]$Repository = "$env:USERPROFILE\forex-bot",
    [string]$TerminalPath = "C:\Program Files\Exness JO MT5 Terminal\terminal64.exe"
)

$ErrorActionPreference = "Stop"
$python = Join-Path $Repository ".venv\Scripts\python.exe"
$runtime = Join-Path $Repository "runtime"
$passwordFile = Join-Path $runtime "secrets\mt5_demo_password.dpapi"
$loginFile = Join-Path $runtime "mt5_expected_login.txt"
$serverFile = Join-Path $runtime "mt5_demo_server.txt"
$logFile = Join-Path $runtime "indicator-native-24h.log"
$errorFile = Join-Path $runtime "indicator-native-24h-error.log"

if (-not (Test-Path -LiteralPath $python)) { throw "AAQTS Python not found: $python" }
if (-not (Test-Path -LiteralPath $TerminalPath)) { throw "MT5 terminal not found: $TerminalPath" }
if (-not (Test-Path -LiteralPath $loginFile)) { throw "Pinned demo login missing: $loginFile" }
if (-not (Test-Path -LiteralPath $passwordFile)) { throw "Saved demo password missing: $passwordFile" }
if (-not (Test-Path -LiteralPath $serverFile)) { throw "Saved demo server missing: $serverFile" }

New-Item -ItemType Directory -Path $runtime -Force | Out-Null
Set-Location $Repository
$env:PYTHONPATH = $Repository

# Stop standard AAQTS engine and any prior indicator-only workers.
$task = Get-ScheduledTask -TaskName "AAQTS-Demo-Engine" -ErrorAction SilentlyContinue
if ($task) { Stop-ScheduledTask -TaskName "AAQTS-Demo-Engine" -ErrorAction SilentlyContinue }
Get-CimInstance Win32_Process |
    Where-Object {
        $_.Name -eq "python.exe" -and (
            $_.CommandLine -match "forex-bot.*main\.py" -or
            $_.CommandLine -match "indicator_only_24h\.py" -or
            $_.CommandLine -match "indicator_native_24h\.py"
        )
    } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 2

$securePassword = Get-Content -LiteralPath $passwordFile -Raw | ConvertTo-SecureString
$env:AAQTS_EXECUTION_MODE = "MT5_DEMO"
$env:AAQTS_ACCOUNT_ID = "exness_demo"
$env:AAQTS_RUNTIME_DIR = $runtime
$env:AAQTS_MT5_TERMINAL_PATH = $TerminalPath
$env:AAQTS_MT5_SYMBOL_SUFFIX = "m"
$env:AAQTS_MT5_EXPECTED_LOGIN_FILE = $loginFile
$env:AAQTS_MT5_LOGIN = (Get-Content -LiteralPath $loginFile -Raw).Trim()
$env:AAQTS_MT5_PASSWORD = [System.Net.NetworkCredential]::new('', $securePassword).Password
$env:AAQTS_MT5_SERVER = (Get-Content -LiteralPath $serverFile -Raw).Trim()
$env:AAQTS_MT5_USE_PREAUTHENTICATED_SESSION = "false"

# Native indicator test settings.
$env:AAQTS_INDICATOR_DURATION_HOURS = "24"
$env:AAQTS_INDICATOR_NATIVE_POLL_SECONDS = "1.0"
$env:AAQTS_INDICATOR_NATIVE_HISTORY_BARS = "500"
$env:AAQTS_INDICATOR_FIXED_LOT = "0.05"
$env:AAQTS_INDICATOR_STOP_PERCENT = "1.0"
$env:AAQTS_INDICATOR_MAX_SPREAD_STOP_RATIO = "0.35"

Write-Host "AAQTS INDICATOR_NATIVE_24H"
Write-Host "Data: Exness MT5 BTCUSDm live M15 candles"
Write-Host "Timeframe: 15m HARD LOCK"
Write-Host "LuxAlgo: Swings 5 | Wicks + Outbreaks & Retest | Extend ON | Max bars 300"
Write-Host "AlgoAlpha: Amplitude 2 | Channel Deviation 2 | Linear Regression 7"
Write-Host "Poll interval: 1 second"
Write-Host "Normal AAQTS Demo Engine: PAUSED"
Write-Host "TP rule: next opposite signal closes current trade and immediately opens next trade"

$previous = $ErrorActionPreference
$ErrorActionPreference = "Continue"
try {
    & $python .\scripts\indicator_native_24h.py 1>> $logFile 2>> $errorFile
    $exitCode = $LASTEXITCODE
} finally {
    $ErrorActionPreference = $previous
    if ($task) { Start-ScheduledTask -TaskName "AAQTS-Demo-Engine" -ErrorAction SilentlyContinue }
}
exit $exitCode
