param(
    [string]$Repository = "$env:USERPROFILE\forex-bot"
)

$ErrorActionPreference = "Stop"
$runtime = Join-Path $Repository "runtime"
$secretDir = Join-Path $runtime "secrets"
$loginFile = Join-Path $runtime "winprofx_live_login.txt"
$serverFile = Join-Path $runtime "winprofx_live_server.txt"
$passwordFile = Join-Path $secretDir "winprofx_live_password.dpapi"

New-Item -ItemType Directory -Path $secretDir -Force | Out-Null

$login = (Read-Host "WinProFX MT5 login").Trim()
if ($login -notmatch '^\d+$') { throw "MT5 login must contain digits only" }
$server = (Read-Host "Exact WinProFX MT5 server").Trim()
if ([string]::IsNullOrWhiteSpace($server)) { throw "MT5 server is required" }
$password = Read-Host "WinProFX MT5 trading password" -AsSecureString

$login | Set-Content -LiteralPath $loginFile -Encoding ASCII
$server | Set-Content -LiteralPath $serverFile -Encoding UTF8
$password | ConvertFrom-SecureString | Set-Content -LiteralPath $passwordFile -Encoding ASCII

"WINPROFX_LIVE_CREDENTIALS_SAVED"
"LOGIN=$login"
"SERVER=$server"
"PASSWORD=DPAPI_ENCRYPTED"
