param(
    [string]$Repository = "$env:USERPROFILE\forex-bot",
    [string]$TerminalPath = "C:\Program Files\Exness JO MT5 Terminal\terminal64.exe"
)

$ErrorActionPreference = "Stop"
$python = Join-Path $Repository ".venv\Scripts\python.exe"
$secretDir = Join-Path $Repository "runtime\secrets"
$passwordFile = Join-Path $secretDir "mt5_demo_password.dpapi"
$loginFile = Join-Path $Repository "runtime\mt5_expected_login.txt"
$serverFile = Join-Path $Repository "runtime\mt5_demo_server.txt"

if (-not (Test-Path -LiteralPath $python)) {
    throw "AAQTS Python was not found: $python"
}
if (-not (Test-Path -LiteralPath $TerminalPath)) {
    throw "MT5 terminal was not found: $TerminalPath"
}

New-Item -ItemType Directory -Path $secretDir -Force | Out-Null
Set-Location $Repository

# Read the identity from the terminal that the operator has visibly selected.
$identity = & $python -c "import MetaTrader5 as m; p=r'$TerminalPath'; assert m.initialize(path=p,timeout=60000),m.last_error(); a=m.account_info(); assert a and a.trade_mode==m.ACCOUNT_TRADE_MODE_DEMO,'DEMO ACCOUNT REQUIRED'; print(f'{a.login}|{a.server}'); m.shutdown()"
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($identity)) {
    throw "Could not read the authenticated MT5 demo account"
}
$parts = $identity.Trim().Split('|')
if ($parts.Count -ne 2 -or $parts[0] -notmatch '^\d+$' -or [string]::IsNullOrWhiteSpace($parts[1])) {
    throw "MT5 returned an invalid account identity"
}

$securePassword = Read-Host "MT5 demo trading password" -AsSecureString
$plainPassword = [System.Net.NetworkCredential]::new('', $securePassword).Password
try {
    $env:AAQTS_SETUP_MT5_PASSWORD = $plainPassword
    $env:AAQTS_SETUP_MT5_LOGIN = $parts[0]
    $env:AAQTS_SETUP_MT5_SERVER = $parts[1]
    & $python -c "import os,MetaTrader5 as m; p=r'$TerminalPath'; ok=m.initialize(path=p,login=int(os.environ['AAQTS_SETUP_MT5_LOGIN']),password=os.environ['AAQTS_SETUP_MT5_PASSWORD'],server=os.environ['AAQTS_SETUP_MT5_SERVER'],timeout=60000); assert ok,m.last_error(); a=m.account_info(); assert a and a.trade_mode==m.ACCOUNT_TRADE_MODE_DEMO,'DEMO ACCOUNT REQUIRED'; assert str(a.login)==os.environ['AAQTS_SETUP_MT5_LOGIN'],'UNEXPECTED ACCOUNT'; m.shutdown(); print('MT5_DEMO_CREDENTIALS=VERIFIED')"
    if ($LASTEXITCODE -ne 0) {
        throw "The supplied MT5 demo credentials were rejected"
    }

    $securePassword | ConvertFrom-SecureString | Set-Content -LiteralPath $passwordFile
    Set-Content -LiteralPath $loginFile -Value $parts[0] -NoNewline
    Set-Content -LiteralPath $serverFile -Value $parts[1] -NoNewline
    "DEMO_CREDENTIALS=SAVED_FOR_CURRENT_WINDOWS_USER"
} finally {
    Remove-Item Env:\AAQTS_SETUP_MT5_PASSWORD -ErrorAction SilentlyContinue
    Remove-Item Env:\AAQTS_SETUP_MT5_LOGIN -ErrorAction SilentlyContinue
    Remove-Item Env:\AAQTS_SETUP_MT5_SERVER -ErrorAction SilentlyContinue
    $plainPassword = $null
}
