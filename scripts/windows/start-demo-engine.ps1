param(
    [string]$Repository = "$env:USERPROFILE\forex-bot",
    [string]$TerminalPath = "C:\Program Files\Exness JO MT5 Terminal\terminal64.exe"
)

$ErrorActionPreference = "Stop"
$python = Join-Path $Repository ".venv\Scripts\python.exe"
$runtime = Join-Path $Repository "runtime"
$passwordFile = Join-Path $runtime "secrets\mt5_demo_password.dpapi"
$openaiKeyFile = Join-Path $runtime "secrets\openai_api_key.dpapi"
$loginFile = Join-Path $runtime "mt5_expected_login.txt"
$serverFile = Join-Path $runtime "mt5_demo_server.txt"
$profileFile = Join-Path $runtime "utbot_runtime_profile.json"

if (-not (Test-Path -LiteralPath $python)) { throw "AAQTS Python was not found: $python" }
$certFile = (& $python -m certifi).Trim()
if (-not (Test-Path -LiteralPath $certFile)) { throw "Trusted CA bundle was not found: $certFile" }
$env:SSL_CERT_FILE = $certFile
if (-not (Test-Path -LiteralPath $TerminalPath)) { throw "MT5 terminal was not found: $TerminalPath" }
New-Item -ItemType Directory -Path $runtime -Force | Out-Null
Set-Location $Repository

$env:AAQTS_EXECUTION_MODE = "MT5_DEMO"
$env:AAQTS_ACCOUNT_ID = "exness_demo"
$env:AAQTS_RUNTIME_DIR = $runtime
$env:AAQTS_SINGLE_ACCOUNT_MODE = "true"
$env:AAQTS_PRIMARY_ACCOUNT_ID = "exness_demo"
$env:AAQTS_MARKET_DATA_PROVIDER = "MT5"
$env:AAQTS_MT5_TERMINAL_PATH = $TerminalPath
$env:AAQTS_MT5_SYMBOL_SUFFIX = "m"
$env:AAQTS_MT5_EXPECTED_LOGIN_FILE = $loginFile

if ((Test-Path -LiteralPath $passwordFile) -and (Test-Path -LiteralPath $loginFile) -and (Test-Path -LiteralPath $serverFile)) {
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

$env:AAQTS_AI_CHART_ENABLED = "true"
$env:AAQTS_AI_CHART_REMOTE_ENABLED = "false"
Remove-Item Env:OPENAI_API_KEY -ErrorAction SilentlyContinue

if ($env:AAQTS_AI_CHART_REMOTE_ENABLED -eq "true" -and (Test-Path -LiteralPath $openaiKeyFile)) {
    $secureOpenAIKey = Get-Content -LiteralPath $openaiKeyFile -Raw | ConvertTo-SecureString
    $env:OPENAI_API_KEY = [System.Net.NetworkCredential]::new('', $secureOpenAIKey).Password
}

$env:AAQTS_AI_CHART_MODE = "OBSERVER"
$env:AAQTS_AI_CHART_MODEL = "gpt-5"
$env:AAQTS_AI_CHART_ONLY_ACTIONABLE = "true"
$env:AAQTS_AI_CHART_MAX_INFLIGHT = "2"
$env:AAQTS_AI_CHART_LOWER_RENDER_BARS = "96"
$env:AAQTS_AI_CHART_HIGHER_RENDER_BARS = "96"
$env:AAQTS_AI_CHART_NUMERIC_BARS = "24"
$env:AAQTS_AI_CHART_TIMEOUT_SECONDS = "30"
$env:AAQTS_AI_CHART_IMAGE_DETAIL = "high"
$env:AAQTS_AI_CHART_MAX_OUTPUT_TOKENS = "1400"
$env:AAQTS_AI_CHART_PROMPT_VERSION = "aaqts_chart_v1.0"

# Keep observer-only evidence separate from every legacy strategy cohort.
$env:AAQTS_AI_CHART_OUTPUT_ROOT = "runtime/ai_chart_analysis_utbot"

$env:AAQTS_AI_CHART_OUTCOMES_ENABLED = "true"
$env:AAQTS_AI_CHART_OUTCOME_HORIZONS = "1,3,6,12"
$env:AAQTS_AI_CHART_OUTCOME_STOP_R = "1.0"
$env:AAQTS_AI_CHART_OUTCOME_TARGET_R = "2.0"

$env:AAQTS_AI_CHART_ANALYTICS_ENABLED = "true"
$env:AAQTS_AI_CHART_ANALYTICS_MIN_FINALIZED = "30"
$env:AAQTS_AI_CHART_ANALYTICS_MIN_BUCKET = "10"

# UT Bot is the only active indicator decision policy. Legacy
# ADX/regime/RSI/MACD/Bollinger/context thresholds are intentionally absent.
# Entries remain pure UT Bot. Every order receives a broker-side ATR stop;
# at +1R it moves to break-even and from +1.5R it trails by 2.5 ATR. There is
# no fixed TP cap, while an opposite UT signal remains a final exit.
$env:AAQTS_STRATEGY_MODE = "UT_BOT"
$env:AAQTS_UTBOT_KEY_VALUE = "3.0"
$env:AAQTS_UTBOT_ATR_PERIOD = "10"
$env:AAQTS_UTBOT_SIGNAL_CONFIDENCE = "80"
$env:AAQTS_UTBOT_EXIT_MODE = "ATR_TRAIL"
$env:AAQTS_UTBOT_INITIAL_SL_ATR_MULTIPLIER = "1.5"
$env:AAQTS_UTBOT_BREAK_EVEN_TRIGGER_R = "1.0"
$env:AAQTS_UTBOT_TRAILING_START_R = "1.5"
$env:AAQTS_UTBOT_TRAILING_ATR_MULTIPLIER = "2.5"
$env:AAQTS_RISK_PERCENT = "0.5"
$env:AAQTS_MT5_MAX_OPEN_POSITIONS = "3"
$env:AAQTS_MT5_MAX_SPREAD_STOP_RATIO = "0.35"
$env:AAQTS_MAX_CONSECUTIVE_LOSSES = "0"
$env:AAQTS_MAX_DAILY_TRADES = "0"
$env:AAQTS_NEWS_FILTER_ENABLED = "true"
$env:AAQTS_DISABLED_BROKER_SYMBOLS = "XAUUSD,XAGUSD,XPTUSD,XPDUSD"
$env:AAQTS_MT5_STOP_LOSS_COOLDOWN_MINUTES = "0"
$env:AAQTS_BOT_INTERVAL_SECONDS = "1"
$env:AAQTS_POSITION_MANAGEMENT_INTERVAL_SECONDS = "1"
$env:PYTHONUNBUFFERED = "1"

$runtimeProfile = [ordered]@{
    profile = "utbot_atr_trail_v1"
    generated_utc = (Get-Date).ToUniversalTime().ToString("o")
    execution_mode = $env:AAQTS_EXECUTION_MODE
    research_output_root = $env:AAQTS_AI_CHART_OUTPUT_ROOT
    strategy_mode = $env:AAQTS_STRATEGY_MODE
    utbot_key_value = [double]$env:AAQTS_UTBOT_KEY_VALUE
    utbot_atr_period = [int]$env:AAQTS_UTBOT_ATR_PERIOD
    utbot_signal_confidence = [int]$env:AAQTS_UTBOT_SIGNAL_CONFIDENCE
    exit_mode = $env:AAQTS_UTBOT_EXIT_MODE
    initial_sl_atr = [double]$env:AAQTS_UTBOT_INITIAL_SL_ATR_MULTIPLIER
    break_even_trigger_r = [double]$env:AAQTS_UTBOT_BREAK_EVEN_TRIGGER_R
    trailing_start_r = [double]$env:AAQTS_UTBOT_TRAILING_START_R
    trailing_atr = [double]$env:AAQTS_UTBOT_TRAILING_ATR_MULTIPLIER
    risk_percent = [double]$env:AAQTS_RISK_PERCENT
    max_open_positions = [int]$env:AAQTS_MT5_MAX_OPEN_POSITIONS
    scan_interval_seconds = [int]$env:AAQTS_BOT_INTERVAL_SECONDS
    max_consecutive_losses = [int]$env:AAQTS_MAX_CONSECUTIVE_LOSSES
    max_daily_trades = [int]$env:AAQTS_MAX_DAILY_TRADES
    stop_loss_cooldown_minutes = [int]$env:AAQTS_MT5_STOP_LOSS_COOLDOWN_MINUTES
    news_filter_enabled = ($env:AAQTS_NEWS_FILTER_ENABLED -eq "true")
    remote_ai_enabled = ($env:AAQTS_AI_CHART_REMOTE_ENABLED -eq "true")
}
$runtimeProfile | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath $profileFile -Encoding UTF8

$previousEAP = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& $python main.py 1>> (Join-Path $runtime "demo-engine.log") 2>> (Join-Path $runtime "demo-engine-error.log")
$pythonExitCode = $LASTEXITCODE
$ErrorActionPreference = $previousEAP
exit $pythonExitCode
