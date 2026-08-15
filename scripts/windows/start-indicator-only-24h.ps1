param(
    [string]$Repository = "$env:USERPROFILE\forex-bot",
    [string]$TerminalPath = "C:\Program Files\Exness JO MT5 Terminal\terminal64.exe",
    [string]$AllowedSymbols = "BTCUSD"
)

$ErrorActionPreference = "Stop"
$python = Join-Path $Repository ".venv\Scripts\python.exe"
$runtime = Join-Path $Repository "runtime"
$passwordFile = Join-Path $runtime "secrets\mt5_demo_password.dpapi"
$loginFile = Join-Path $runtime "mt5_expected_login.txt"
$serverFile = Join-Path $runtime "mt5_demo_server.txt"
$logFile = Join-Path $runtime "indicator-only-24h.log"
$errorFile = Join-Path $runtime "indicator-only-24h-error.log"

if (-not (Test-Path -LiteralPath $python)) { throw "AAQTS Python not found: $python" }
if (-not (Test-Path -LiteralPath $TerminalPath)) { throw "MT5 terminal not found: $TerminalPath" }
if (-not (Test-Path -LiteralPath $loginFile)) { throw "Pinned demo login file missing: $loginFile" }
New-Item -ItemType Directory -Path $runtime -Force | Out-Null
Set-Location $Repository

# Pause the normal AAQTS engine so this temporary experiment owns execution.
$task = Get-ScheduledTask -TaskName "AAQTS-Demo-Engine" -ErrorAction SilentlyContinue
if ($task) {
    Stop-ScheduledTask -TaskName "AAQTS-Demo-Engine" -ErrorAction SilentlyContinue
}
Start-Sleep -Seconds 2
Get-CimInstance Win32_Process |
    Where-Object {
        $_.Name -eq "python.exe" -and
        $_.CommandLine -match "forex-bot.*main\.py"
    } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 2

# Reuse the same demo authentication policy as the normal engine launcher.
$env:AAQTS_EXECUTION_MODE = "MT5_DEMO"
$env:AAQTS_ACCOUNT_ID = "exness_demo"
$env:AAQTS_RUNTIME_DIR = $runtime
$env:AAQTS_MT5_TERMINAL_PATH = $TerminalPath
$env:AAQTS_MT5_SYMBOL_SUFFIX = "m"
$env:AAQTS_MT5_EXPECTED_LOGIN_FILE = $loginFile

if ((Test-Path -LiteralPath $passwordFile) -and (Test-Path -LiteralPath $serverFile)) {
    $securePassword = Get-Content -LiteralPath $passwordFile -Raw | ConvertTo-SecureString
    $env:AAQTS_MT5_LOGIN = (Get-Content -LiteralPath $loginFile -Raw).Trim()
    $env:AAQTS_MT5_PASSWORD = [System.Net.NetworkCredential]::new('', $securePassword).Password
    $env:AAQTS_MT5_SERVER = (Get-Content -LiteralPath $serverFile -Raw).Trim()
    $env:AAQTS_MT5_USE_PREAUTHENTICATED_SESSION = "false"
} else {
    $env:AAQTS_MT5_USE_PREAUTHENTICATED_SESSION = "true"
    $env:AAQTS_MT5_LOGIN = ""
    $env:AAQTS_MT5_PASSWORD = ""
    $env:AAQTS_MT5_SERVER = ""
}

$env:AAQTS_INDICATOR_ALLOWED_SYMBOLS = $AllowedSymbols
$env:AAQTS_INDICATOR_DURATION_HOURS = "24"
$env:AAQTS_INDICATOR_POLL_SECONDS = "5"
$env:AAQTS_INDICATOR_FIXED_LOT = "0.05"
$env:AAQTS_INDICATOR_STOP_PERCENT = "1.0"
$env:AAQTS_INDICATOR_MAX_SPREAD_STOP_RATIO = "0.35"

Write-Host "AAQTS UTBOT_EMA200_24H"
Write-Host "Timeframe: 15m CLOSED CANDLES"
Write-Host "UT Bot: Key Value 3 / ATR Period 10"
Write-Host "EMA filter: 200"
Write-Host "Symbols: $AllowedSymbols"
Write-Host "Normal AAQTS Demo Engine: PAUSED"
Write-Host "Entry: BUY only above EMA200; SELL only below EMA200"
Write-Host "Exit: next opposite UT Bot signal"
Write-Host "Reverse entry: only if new side passes EMA200 filter"
Write-Host "Emergency broker stop: 1% catastrophe protection"

$previous = $ErrorActionPreference
$ErrorActionPreference = "Continue"
try {
    & $python .\scripts\indicator_only_24h.py 1>> $logFile 2>> $errorFile
    $exitCode = $LASTEXITCODE
} finally {
    $ErrorActionPreference = $previous
    # Restore normal AAQTS after the 24-hour experiment ends or is stopped.
    if ($task) {
        Start-ScheduledTask -TaskName "AAQTS-Demo-Engine" -ErrorAction SilentlyContinue
    }
}
exit $exitCode
