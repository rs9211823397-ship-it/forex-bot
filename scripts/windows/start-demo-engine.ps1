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

$env:AAQTS_MT5_MAX_OPEN_POSITIONS = "5"
$env:AAQTS_RISK_PERCENT = "1.0"
$env:AAQTS_NEWS_FILTER_ENABLED = "true"
$env:AAQTS_DISABLED_BROKER_SYMBOLS = "XAUUSD,XAGUSD,XPTUSD,XPDUSD"
$env:AAQTS_MT5_STOP_LOSS_COOLDOWN_MINUTES = "60"
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
