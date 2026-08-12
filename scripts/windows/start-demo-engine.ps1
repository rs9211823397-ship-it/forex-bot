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
    # This is explicit and overrides stale credentials in .env. It is suitable
    # only while the desktop MT5 session remains authenticated.
    $env:AAQTS_MT5_USE_PREAUTHENTICATED_SESSION = "true"
    $env:AAQTS_MT5_LOGIN = ""
    $env:AAQTS_MT5_PASSWORD = ""
    $env:AAQTS_MT5_SERVER = ""
}

# Phase AI-1 local evidence collection is enabled, but remote model calls are
# intentionally disabled while the account has no API credits. The saved DPAPI
# key remains on disk and is not decrypted into this process in capture-only mode.
$env:AAQTS_AI_CHART_ENABLED = "true"
$env:AAQTS_AI_CHART_REMOTE_ENABLED = "false"
Remove-Item Env:OPENAI_API_KEY -ErrorAction SilentlyContinue

# When remote analysis is deliberately re-enabled later, the existing DPAPI key
# can be loaded without re-entering it.
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
$env:AAQTS_AI_CHART_OUTPUT_ROOT = "runtime/ai_chart_analysis"

# Forward-only local outcome labels. These do not use OpenAI and do not affect
# strategy, risk, execution, or position management.
$env:AAQTS_AI_CHART_OUTCOMES_ENABLED = "true"
$env:AAQTS_AI_CHART_OUTCOME_HORIZONS = "1,3,6,12"
$env:AAQTS_AI_CHART_OUTCOME_STOP_R = "1.0"
$env:AAQTS_AI_CHART_OUTCOME_TARGET_R = "2.0"

$env:AAQTS_MT5_FIXED_LOT = "0.05"
$env:AAQTS_MT5_MAX_OPEN_POSITIONS = "5"
$env:AAQTS_MT5_MAX_SPREAD_STOP_RATIO = "0.35"
$env:AAQTS_RISK_PERCENT = "1.0"
$env:AAQTS_MAX_CONSECUTIVE_LOSSES = "0"
$env:AAQTS_MAX_DAILY_TRADES = "0"
$env:AAQTS_NEWS_FILTER_ENABLED = "true"
$env:AAQTS_DISABLED_BROKER_SYMBOLS = "XAUUSD,XAGUSD,XPTUSD,XPDUSD"
$env:AAQTS_MT5_STOP_LOSS_COOLDOWN_MINUTES = "0"
$env:AAQTS_BOT_INTERVAL_SECONDS = "300"
$env:AAQTS_POSITION_MANAGEMENT_INTERVAL_SECONDS = "10"
$env:AAQTS_MIN_ADX = "12"
$env:AAQTS_SIGNAL_SCORE_THRESHOLD = "35"
$env:AAQTS_MIN_SIGNAL_CONFIRMATIONS = "1"
$env:AAQTS_MIN_TRADE_QUALITY = "35"
$env:AAQTS_PORTFOLIO_MAX_ABS_CORRELATION = "0.95"
$env:AAQTS_PORTFOLIO_MAX_CORRELATED_RISK_PERCENT = "5.0"
$env:AAQTS_MIN_REGIME_CONFIDENCE = "35"
$env:PYTHONUNBUFFERED = "1"

$previousEAP = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& $python main.py 1>> (Join-Path $runtime "demo-engine.log") 2>> (Join-Path $runtime "demo-engine-error.log")
$pythonExitCode = $LASTEXITCODE
$ErrorActionPreference = $previousEAP
exit $pythonExitCode
