param(
    [string]$Repository = "$env:USERPROFILE\forex-bot"
)

$ErrorActionPreference = "Stop"
$python = Join-Path $Repository ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $python)) {
    throw "AAQTS Python was not found: $python"
}
if (-not (Test-Path -LiteralPath (Join-Path $Repository "main.py"))) {
    throw "AAQTS repository was not found: $Repository"
}

Set-Location $Repository
& $python -m compileall -q .
if ($LASTEXITCODE -ne 0) { throw "Python compile validation failed" }

& $python scripts\security_check.py
if ($LASTEXITCODE -ne 0) { throw "Security validation failed" }

$pytestReady = (& $python -c "import importlib.util; print(importlib.util.find_spec('pytest') is not None)").Trim()
if ($pytestReady -eq "True") {
    & $python -m pytest -q `
        tests\test_mt5_executor.py `
        tests\test_execution_router.py `
        tests\test_position_manager_runtime.py `
        tests\test_ut_bot_ema200_strategy.py
    if ($LASTEXITCODE -ne 0) { throw "Protected UT Bot tests failed" }
}

"UTBOT_ATR_TRAIL_CODE_VALID"
"No trading process was stopped or started."
"Next: save WinProFX credentials, run live preflight, then start the live engine."
