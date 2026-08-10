param(
    [string]$Repository = "$env:USERPROFILE\forex-bot"
)

$ErrorActionPreference = "Stop"
$python = Join-Path $Repository ".venv\Scripts\python.exe"
$runtime = Join-Path $Repository "runtime"
$tokenFile = Join-Path $runtime "secrets\telegram_token.dpapi"

if (-not (Test-Path -LiteralPath $python)) { throw "AAQTS Python was not found: $python" }
$certFile = (& $python -m certifi).Trim()
if (-not (Test-Path -LiteralPath $certFile)) { throw "Trusted CA bundle was not found: $certFile" }
$env:SSL_CERT_FILE = $certFile
if (-not (Test-Path -LiteralPath $tokenFile)) { throw "Encrypted Telegram token was not found: $tokenFile" }
New-Item -ItemType Directory -Path $runtime -Force | Out-Null
Set-Location $Repository

$encryptedToken = [System.IO.File]::ReadAllText($tokenFile).Trim()
$secureToken = ConvertTo-SecureString -String $encryptedToken
$env:TELEGRAM_BOT_TOKEN = [System.Net.NetworkCredential]::new('', $secureToken).Password
$env:AAQTS_RUNTIME_DIR = $runtime
$env:AAQTS_SINGLE_ACCOUNT_MODE = "true"
$env:AAQTS_PRIMARY_ACCOUNT_ID = "exness_demo"
$env:AAQTS_ACCOUNT_ID = "exness_demo"
$env:AAQTS_EXECUTION_MODE = "MT5_DEMO"
$env:AAQTS_MARKET_DATA_PROVIDER = "MT5"
$env:AAQTS_MT5_TERMINAL_PATH = "C:\Program Files\Exness JO MT5 Terminal\terminal64.exe"
$env:AAQTS_MT5_SYMBOL_SUFFIX = "m"
$env:AAQTS_MT5_USE_PREAUTHENTICATED_SESSION = "true"
$env:AAQTS_MT5_LOGIN = ""
$env:AAQTS_MT5_PASSWORD = ""
$env:AAQTS_MT5_SERVER = ""
$env:AAQTS_DISABLED_BROKER_SYMBOLS = "XAUUSD,XAGUSD,XPTUSD,XPDUSD"

$previousEAP = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& $python -m telegram_bot.bot 1>> (Join-Path $runtime "telegram.log") 2>> (Join-Path $runtime "telegram-error.log")
$pythonExitCode = $LASTEXITCODE
$ErrorActionPreference = $previousEAP
exit $pythonExitCode
