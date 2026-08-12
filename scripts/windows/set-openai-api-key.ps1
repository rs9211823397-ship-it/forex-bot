param(
    [string]$Repository = "$env:USERPROFILE\forex-bot"
)

$ErrorActionPreference = "Stop"
$runtime = Join-Path $Repository "runtime"
$secrets = Join-Path $runtime "secrets"
$keyFile = Join-Path $secrets "openai_api_key.dpapi"

New-Item -ItemType Directory -Path $secrets -Force | Out-Null

$secureKey = Read-Host "Paste the OpenAI API key (input is hidden)" -AsSecureString
$encrypted = $secureKey | ConvertFrom-SecureString
if ([string]::IsNullOrWhiteSpace($encrypted)) {
    throw "No API key was provided."
}

Set-Content -LiteralPath $keyFile -Value $encrypted -NoNewline -Encoding UTF8
Write-Host "OPENAI_API_KEY stored with Windows DPAPI at: $keyFile"
Write-Host "The plaintext key was not written to the repository or console output."
