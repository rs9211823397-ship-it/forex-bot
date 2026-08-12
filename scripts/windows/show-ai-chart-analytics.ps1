param(
    [string]$Repository = "$env:USERPROFILE\forex-bot"
)

$ErrorActionPreference = "Stop"
$python = Join-Path $Repository ".venv\Scripts\python.exe"
$summaryPath = Join-Path $Repository "runtime\ai_chart_analysis\analytics_summary.json"

if (-not (Test-Path -LiteralPath $python)) {
    throw "AAQTS Python was not found: $python"
}

Set-Location $Repository

# Refresh from persisted capture/outcome evidence. This makes no network calls.
& $python -c "from ai.chart_analysis.analytics import OutcomeAnalytics; from ai.chart_analysis.config import ChartObserverConfig; OutcomeAnalytics(ChartObserverConfig.from_env()).refresh()" | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Could not refresh AAQTS chart analytics"
}

if (-not (Test-Path -LiteralPath $summaryPath)) {
    throw "Analytics summary was not created: $summaryPath"
}

$s = Get-Content -LiteralPath $summaryPath -Raw | ConvertFrom-Json
$readiness = if ($s.readiness.ready_for_overall_conclusions) { "READY" } else { "NOT_READY" }

Write-Host ""
Write-Host "AAQTS CHART OUTCOME ANALYTICS"
Write-Host "Generated UTC: $($s.generated_utc)"
Write-Host "Readiness: $readiness"
Write-Host "Guardrail: $($s.readiness.minimum_finalized_samples) finalized overall / $($s.readiness.minimum_bucket_samples) per bucket"
Write-Host ""

[PSCustomObject]@{
    Captures = $s.counts.captures
    Pending = $s.counts.pending
    Finalized = $s.counts.finalized
    Errors = $s.counts.errors
    ExpectancyR = $s.overall.expectancy_r
    MedianR = $s.overall.median_r
    ProfitFactor = $s.overall.profit_factor
    PositiveRate = $s.overall.positive_r_rate
    TotalR = $s.overall.total_r
} | Format-List

Write-Host "HORIZONS"
$horizonRows = foreach ($property in $s.horizons.PSObject.Properties) {
    $h = $property.Value
    [PSCustomObject]@{
        Bars = [int]$property.Name
        Samples = $h.samples
        AvgMtMR = $h.avg_mark_to_market_r
        AvgMFER = $h.avg_mfe_r
        AvgMAER = $h.avg_mae_r
        PositiveCloseRate = $h.positive_close_rate
    }
}
$horizonRows | Sort-Object Bars | Format-Table -AutoSize

Write-Host "BY SYMBOL"
$symbolRows = foreach ($property in $s.by_symbol.PSObject.Properties) {
    $b = $property.Value
    [PSCustomObject]@{
        Symbol = $property.Name
        Captures = $b.captures
        Pending = $b.pending
        Finalized = $b.final.samples
        ExpectancyR = $b.final.expectancy_r
        ProfitFactor = $b.final.profit_factor
        Guardrail = if ($b.sample_guardrail_met) { "READY" } else { "NOT_READY" }
    }
}
$symbolRows | Sort-Object Symbol | Format-Table -AutoSize

Write-Host ""
Write-Host $s.readiness.warning
