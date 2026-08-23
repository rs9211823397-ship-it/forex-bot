param(
    [string]$Repository = "$env:USERPROFILE\forex-bot",
    [Parameter(Mandatory=$true)][string]$TerminalPath,
    [string]$SymbolSuffix = "",
    [string]$AccountId = "winprofx_live"
)

$ErrorActionPreference = "Stop"
$python = Join-Path $Repository ".venv\Scripts\python.exe"
$runtime = Join-Path $Repository "runtime"
$passwordFile = Join-Path $runtime "secrets\winprofx_live_password.dpapi"
$loginFile = Join-Path $runtime "winprofx_live_login.txt"
$serverFile = Join-Path $runtime "winprofx_live_server.txt"
$profileFile = Join-Path $runtime "utbot_live_runtime_profile.json"

foreach ($required in @($python, $TerminalPath, $passwordFile, $loginFile, $serverFile)) {
    if (-not (Test-Path -LiteralPath $required)) { throw "Required live file was not found: $required" }
}

New-Item -ItemType Directory -Path $runtime -Force | Out-Null
Set-Location $Repository
$securePassword = Get-Content -LiteralPath $passwordFile -Raw | ConvertTo-SecureString

$env:AAQTS_EXECUTION_MODE = "MT5_LIVE"
$env:AAQTS_LIVE_TRADING_ACK = "I_UNDERSTAND_REAL_MONEY"
$env:AAQTS_ACCOUNT_ID = $AccountId
$env:AAQTS_RUNTIME_DIR = $runtime
$env:AAQTS_SINGLE_ACCOUNT_MODE = "true"
$env:AAQTS_PRIMARY_ACCOUNT_ID = $AccountId
$env:AAQTS_MARKET_DATA_PROVIDER = "MT5"
$env:AAQTS_MT5_TERMINAL_PATH = $TerminalPath
$env:AAQTS_MT5_SYMBOL_SUFFIX = $SymbolSuffix
$env:AAQTS_MT5_USE_PREAUTHENTICATED_SESSION = "false"
$env:AAQTS_MT5_LOGIN = (Get-Content -LiteralPath $loginFile -Raw).Trim()
$env:AAQTS_MT5_EXPECTED_LOGIN = $env:AAQTS_MT5_LOGIN
$env:AAQTS_MT5_PASSWORD = [System.Net.NetworkCredential]::new('', $securePassword).Password
$env:AAQTS_MT5_SERVER = (Get-Content -LiteralPath $serverFile -Raw).Trim()

$env:AAQTS_STRATEGY_MODE = "UT_BOT"
$env:AAQTS_UTBOT_KEY_VALUE = "3.0"
$env:AAQTS_UTBOT_ATR_PERIOD = "10"
$env:AAQTS_UTBOT_SIGNAL_CONFIDENCE = "80"
$env:AAQTS_UTBOT_EXIT_MODE = "ATR_TRAIL"
$env:AAQTS_UTBOT_INITIAL_SL_ATR_MULTIPLIER = "1.5"
$env:AAQTS_UTBOT_BREAK_EVEN_TRIGGER_R = "1.0"
$env:AAQTS_UTBOT_TRAILING_START_R = "1.5"
$env:AAQTS_UTBOT_TRAILING_ATR_MULTIPLIER = "2.5"

# Real-money defaults deliberately risk less than the old demo experiment.
$env:AAQTS_RISK_PERCENT = "0.5"
$env:AAQTS_MT5_MAX_OPEN_POSITIONS = "3"
$env:AAQTS_MAX_PORTFOLIO_RISK_PERCENT = "1.5"
$env:AAQTS_MAX_DAILY_LOSS_PERCENT = "2.0"
$env:AAQTS_MAX_WEEKLY_LOSS_PERCENT = "5.0"
$env:AAQTS_MAX_EQUITY_DRAWDOWN_PERCENT = "8.0"
$env:AAQTS_MT5_MAX_SPREAD_STOP_RATIO = "0.25"
$env:AAQTS_NEWS_FILTER_ENABLED = "true"
$env:AAQTS_MT5_STOP_LOSS_COOLDOWN_MINUTES = "30"
$env:AAQTS_BOT_INTERVAL_SECONDS = "1"
$env:AAQTS_POSITION_MANAGEMENT_INTERVAL_SECONDS = "1"
$env:PYTHONUNBUFFERED = "1"

$profile = [ordered]@{
    profile = "winprofx_utbot_atr_trail_v1"
    generated_utc = (Get-Date).ToUniversalTime().ToString("o")
    execution_mode = $env:AAQTS_EXECUTION_MODE
    account_id = $AccountId
    strategy_mode = $env:AAQTS_STRATEGY_MODE
    exit_mode = $env:AAQTS_UTBOT_EXIT_MODE
    initial_sl_atr = [double]$env:AAQTS_UTBOT_INITIAL_SL_ATR_MULTIPLIER
    break_even_trigger_r = [double]$env:AAQTS_UTBOT_BREAK_EVEN_TRIGGER_R
    trailing_start_r = [double]$env:AAQTS_UTBOT_TRAILING_START_R
    trailing_atr = [double]$env:AAQTS_UTBOT_TRAILING_ATR_MULTIPLIER
    risk_percent = [double]$env:AAQTS_RISK_PERCENT
    max_open_positions = [int]$env:AAQTS_MT5_MAX_OPEN_POSITIONS
    symbol_suffix = $SymbolSuffix
}
$profile | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath $profileFile -Encoding UTF8

& $python scripts\preflight.py
if ($LASTEXITCODE -ne 0) { throw "WinProFX live preflight failed; no engine was started" }

$previousEAP = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& $python main.py 1>> (Join-Path $runtime "live-engine.log") 2>> (Join-Path $runtime "live-engine-error.log")
$pythonExitCode = $LASTEXITCODE
$ErrorActionPreference = $previousEAP
exit $pythonExitCode
