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
$profileFile = Join-Path $runtime "quality_v3_balanced_runtime_profile.json"

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

# Balanced-v3 is a distinct execution policy, so keep its forward-outcome
# evidence separate from the baseline and strict quality-v2 cohorts.
$env:AAQTS_AI_CHART_OUTPUT_ROOT = "runtime/ai_chart_analysis_quality_v3_balanced"

$env:AAQTS_AI_CHART_OUTCOMES_ENABLED = "true"
$env:AAQTS_AI_CHART_OUTCOME_HORIZONS = "1,3,6,12"
$env:AAQTS_AI_CHART_OUTCOME_STOP_R = "1.0"
$env:AAQTS_AI_CHART_OUTCOME_TARGET_R = "2.0"

$env:AAQTS_AI_CHART_ANALYTICS_ENABLED = "true"
$env:AAQTS_AI_CHART_ANALYTICS_MIN_FINALIZED = "30"
$env:AAQTS_AI_CHART_ANALYTICS_MIN_BUCKET = "10"

# Quality-v3-balanced demo profile: lower blunt threshold pressure while
# requiring three confirmations for execution. Count/cooldown stoppages stay
# disabled; hard news, drawdown, margin, spread and portfolio protections stay on.
$env:AAQTS_MT5_FIXED_LOT = "0.05"
$env:AAQTS_MT5_MAX_OPEN_POSITIONS = "3"
$env:AAQTS_MT5_MAX_SPREAD_STOP_RATIO = "0.35"
$env:AAQTS_RISK_PERCENT = "1.0"
$env:AAQTS_MAX_CONSECUTIVE_LOSSES = "0"
$env:AAQTS_MAX_DAILY_TRADES = "0"
$env:AAQTS_NEWS_FILTER_ENABLED = "true"
$env:AAQTS_DISABLED_BROKER_SYMBOLS = "XAUUSD,XAGUSD,XPTUSD,XPDUSD"
$env:AAQTS_MT5_STOP_LOSS_COOLDOWN_MINUTES = "0"
$env:AAQTS_BOT_INTERVAL_SECONDS = "300"
$env:AAQTS_POSITION_MANAGEMENT_INTERVAL_SECONDS = "10"
$env:AAQTS_MIN_ADX = "16"
$env:AAQTS_SIGNAL_SCORE_THRESHOLD = "45"
$env:AAQTS_MIN_SIGNAL_CONFIRMATIONS = "3"
$env:AAQTS_MIN_TRADE_QUALITY = "45"
$env:AAQTS_PORTFOLIO_MAX_ABS_CORRELATION = "0.85"
$env:AAQTS_PORTFOLIO_MAX_CORRELATED_RISK_PERCENT = "4.0"
$env:AAQTS_MIN_REGIME_CONFIDENCE = "40"
$env:PYTHONUNBUFFERED = "1"

$runtimeProfile = [ordered]@{
    profile = "quality_v3_balanced"
    generated_utc = (Get-Date).ToUniversalTime().ToString("o")
    execution_mode = $env:AAQTS_EXECUTION_MODE
    research_output_root = $env:AAQTS_AI_CHART_OUTPUT_ROOT
    fixed_lot = [double]$env:AAQTS_MT5_FIXED_LOT
    risk_percent = [double]$env:AAQTS_RISK_PERCENT
    max_open_positions = [int]$env:AAQTS_MT5_MAX_OPEN_POSITIONS
    max_consecutive_losses = [int]$env:AAQTS_MAX_CONSECUTIVE_LOSSES
    max_daily_trades = [int]$env:AAQTS_MAX_DAILY_TRADES
    stop_loss_cooldown_minutes = [int]$env:AAQTS_MT5_STOP_LOSS_COOLDOWN_MINUTES
    min_adx = [double]$env:AAQTS_MIN_ADX
    signal_score_threshold = [int]$env:AAQTS_SIGNAL_SCORE_THRESHOLD
    min_signal_confirmations = [int]$env:AAQTS_MIN_SIGNAL_CONFIRMATIONS
    min_trade_quality = [int]$env:AAQTS_MIN_TRADE_QUALITY
    min_regime_confidence = [double]$env:AAQTS_MIN_REGIME_CONFIDENCE
    portfolio_max_abs_correlation = [double]$env:AAQTS_PORTFOLIO_MAX_ABS_CORRELATION
    portfolio_max_correlated_risk_percent = [double]$env:AAQTS_PORTFOLIO_MAX_CORRELATED_RISK_PERCENT
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
