param(
    [string]$Repository = "$env:USERPROFILE\forex-bot",
    [string]$TerminalPath = "C:\Program Files\Exness JO MT5 Terminal\terminal64.exe",
    [string]$AllowedSymbols = "BTCUSD",
    [int]$WebhookPort = 80
)

$ErrorActionPreference = "Stop"
$python = Join-Path $Repository ".venv\Scripts\python.exe"
$runtime = Join-Path $Repository "runtime"
$passwordFile = Join-Path $runtime "secrets\mt5_demo_password.dpapi"
$loginFile = Join-Path $runtime "mt5_expected_login.txt"
$serverFile = Join-Path $runtime "mt5_demo_server.txt"
$secretFile = Join-Path $runtime "indicator_only_webhook_secret.txt"
$logFile = Join-Path $runtime "indicator-only-24h.log"
$errorFile = Join-Path $runtime "indicator-only-24h-error.log"

if (-not (Test-Path -LiteralPath $python)) { throw "AAQTS Python not found: $python" }
if (-not (Test-Path -LiteralPath $TerminalPath)) { throw "MT5 terminal not found: $TerminalPath" }
if (-not (Test-Path -LiteralPath $loginFile)) { throw "Pinned demo login file missing: $loginFile" }
New-Item -ItemType Directory -Path $runtime -Force | Out-Null
Set-Location $Repository

$task = Get-ScheduledTask -TaskName "AAQTS-Demo-Engine" -ErrorAction SilentlyContinue
if ($task) { Stop-ScheduledTask -TaskName "AAQTS-Demo-Engine" -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 2
Get-CimInstance Win32_Process |
    Where-Object { $_.Name -eq "python.exe" -and $_.CommandLine -match "forex-bot.*main\.py" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 2

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

if (-not (Test-Path -LiteralPath $secretFile)) {
    $bytes = New-Object byte[] 32
    [System.Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
    Set-Content -LiteralPath $secretFile -Value ([Convert]::ToHexString($bytes).ToLowerInvariant()) -Encoding ascii -NoNewline
}
$env:AAQTS_INDICATOR_WEBHOOK_SECRET = (Get-Content -LiteralPath $secretFile -Raw).Trim()
$env:AAQTS_INDICATOR_ALLOWED_SYMBOLS = $AllowedSymbols
$env:AAQTS_INDICATOR_DURATION_HOURS = "24"
$env:AAQTS_INDICATOR_WEBHOOK_HOST = "0.0.0.0"
$env:AAQTS_INDICATOR_WEBHOOK_PORT = "$WebhookPort"
$env:AAQTS_INDICATOR_FIXED_LOT = "0.05"
$env:AAQTS_INDICATOR_STOP_PERCENT = "1.0"
$env:AAQTS_INDICATOR_MAX_SPREAD_STOP_RATIO = "0.35"

Write-Host "AAQTS INDICATOR_ONLY_24H"
Write-Host "Timeframe: 15m HARD LOCK"
Write-Host "Symbols: $AllowedSymbols"
Write-Host "Webhook port: $WebhookPort"
Write-Host "Webhook secret file: $secretFile"
Write-Host "Normal AAQTS Demo Engine: PAUSED"
Write-Host "TP rule: current trade closes at next opposite signal; same event opens next trade"

$previous = $ErrorActionPreference
$ErrorActionPreference = "Continue"
try {
    & $python .\scripts\indicator_only_24h.py 1>> $logFile 2>> $errorFile
    $exitCode = $LASTEXITCODE
} finally {
    $ErrorActionPreference = $previous
    if ($task) { Start-ScheduledTask -TaskName "AAQTS-Demo-Engine" -ErrorAction SilentlyContinue }
}
exit $exitCode
