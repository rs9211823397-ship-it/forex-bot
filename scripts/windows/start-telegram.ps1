param(
    [string]$Repository = "$env:USERPROFILE\forex-bot"
)

$ErrorActionPreference = "Stop"
$python = Join-Path $Repository ".venv\Scripts\python.exe"
$runtime = Join-Path $Repository "runtime"
$tokenFile = Join-Path $runtime "secrets\telegram_token.dpapi"

if (-not (Test-Path -LiteralPath $python)) { throw "AAQTS Python was not found: $python" }
if (-not (Test-Path -LiteralPath $tokenFile)) { throw "Encrypted Telegram token was not found: $tokenFile" }
New-Item -ItemType Directory -Path $runtime -Force | Out-Null
Set-Location $Repository

$secureToken = Get-Content -LiteralPath $tokenFile -Raw | ConvertTo-SecureString
$env:TELEGRAM_BOT_TOKEN = [System.Net.NetworkCredential]::new('', $secureToken).Password
$env:AAQTS_RUNTIME_DIR = $runtime
$env:AAQTS_SINGLE_ACCOUNT_MODE = "true"
$env:AAQTS_PRIMARY_ACCOUNT_ID = "exness_demo"

& $python -m telegram_bot.bot 1>> (Join-Path $runtime "telegram.log") 2>> (Join-Path $runtime "telegram-error.log")
exit $LASTEXITCODE
