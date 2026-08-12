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

# Research watcher is local analytics + Telegram notification only. It must not
# load or use the OpenAI API key while capture-only mode is active.
Remove-Item Env:OPENAI_API_KEY -ErrorAction SilentlyContinue
$env:AAQTS_AI_CHART_ENABLED = "true"
$env:AAQTS_AI_CHART_REMOTE_ENABLED = "false"
$env:AAQTS_AI_CHART_OUTPUT_ROOT = "runtime/ai_chart_analysis"
$env:AAQTS_AI_CHART_OUTCOMES_ENABLED = "true"
$env:AAQTS_AI_CHART_OUTCOME_HORIZONS = "1,3,6,12"
$env:AAQTS_AI_CHART_ANALYTICS_ENABLED = "true"
$env:AAQTS_AI_CHART_ANALYTICS_MIN_FINALIZED = "30"
$env:AAQTS_AI_CHART_ANALYTICS_MIN_BUCKET = "10"
$env:AAQTS_AI_RESEARCH_WATCH_SECONDS = "60"
$env:PYTHONUNBUFFERED = "1"

$previousEAP = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& $python -m ai.chart_analysis.milestone_watcher 1>> (Join-Path $runtime "ai-research-watcher.log") 2>> (Join-Path $runtime "ai-research-watcher-error.log")
$pythonExitCode = $LASTEXITCODE
$ErrorActionPreference = $previousEAP
exit $pythonExitCode
