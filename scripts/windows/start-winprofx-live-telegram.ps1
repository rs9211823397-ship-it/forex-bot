param(
    [string]$Repository = "$env:USERPROFILE\forex-bot",
    [Parameter(Mandatory=$true)][string]$TerminalPath,
    [string]$SymbolSuffix = "",
    [string]$AccountId = "winprofx_live"
)

$ErrorActionPreference = "Stop"
$python = Join-Path $Repository ".venv\Scripts\python.exe"
$runtime = Join-Path $Repository "runtime"
$tokenFile = Join-Path $runtime "secrets\telegram_token.dpapi"
$passwordFile = Join-Path $runtime "secrets\winprofx_live_password.dpapi"
$loginFile = Join-Path $runtime "winprofx_live_login.txt"
$serverFile = Join-Path $runtime "winprofx_live_server.txt"

foreach ($required in @($python, $TerminalPath, $tokenFile, $passwordFile, $loginFile, $serverFile)) {
    if (-not (Test-Path -LiteralPath $required)) { throw "Required live file was not found: $required" }
}

Set-Location $Repository
$encryptedToken = [System.IO.File]::ReadAllText($tokenFile).Trim()
$encryptedPassword = [System.IO.File]::ReadAllText($passwordFile).Trim()
if ([string]::IsNullOrWhiteSpace($encryptedToken)) { throw "Telegram token secret is empty" }
if ([string]::IsNullOrWhiteSpace($encryptedPassword)) { throw "WinProFX password secret is empty" }
$secureToken = ConvertTo-SecureString -String $encryptedToken
$securePassword = ConvertTo-SecureString -String $encryptedPassword
$env:TELEGRAM_BOT_TOKEN = [System.Net.NetworkCredential]::new('', $secureToken).Password
$env:AAQTS_RUNTIME_DIR = $runtime
$env:AAQTS_SINGLE_ACCOUNT_MODE = "true"
$env:AAQTS_PRIMARY_ACCOUNT_ID = $AccountId
$env:AAQTS_ACCOUNT_ID = $AccountId
$env:AAQTS_EXECUTION_MODE = "MT5_LIVE"
$env:AAQTS_LIVE_TRADING_ACK = "I_UNDERSTAND_REAL_MONEY"
$env:AAQTS_STRATEGY_MODE = "UT_BOT"
$env:AAQTS_UTBOT_EXIT_MODE = "ATR_TRAIL"
$env:AAQTS_MARKET_DATA_PROVIDER = "MT5"
$env:AAQTS_MT5_TERMINAL_PATH = $TerminalPath
$env:AAQTS_MT5_SYMBOL_SUFFIX = $SymbolSuffix
$env:AAQTS_DISABLED_BROKER_SYMBOLS = "XAUUSD,XAGUSD,XPTUSD,XPDUSD,BTCUSD,ETHUSD"
$env:AAQTS_MT5_USE_PREAUTHENTICATED_SESSION = "false"
$env:AAQTS_MT5_LOGIN = (Get-Content -LiteralPath $loginFile -Raw).Trim()
$env:AAQTS_MT5_EXPECTED_LOGIN = $env:AAQTS_MT5_LOGIN
$env:AAQTS_MT5_PASSWORD = [System.Net.NetworkCredential]::new('', $securePassword).Password
$env:AAQTS_MT5_SERVER = (Get-Content -LiteralPath $serverFile -Raw).Trim()

& $python scripts\register_winprofx_live_account.py `
    --runtime-dir $runtime `
    --account-id $AccountId `
    --login $env:AAQTS_MT5_LOGIN `
    --server $env:AAQTS_MT5_SERVER `
    --terminal-path $TerminalPath
if ($LASTEXITCODE -ne 0) { throw "WinProFX Telegram account registration failed" }

$previousEAP = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& $python -m telegram_bot.bot 1>> (Join-Path $runtime "telegram-live.log") 2>> (Join-Path $runtime "telegram-live-error.log")
$pythonExitCode = $LASTEXITCODE
$ErrorActionPreference = $previousEAP
exit $pythonExitCode
