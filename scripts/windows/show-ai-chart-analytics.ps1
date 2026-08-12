param(
    [string]$Repository = "$env:USERPROFILE\forex-bot",
    [string]$OutputRoot = "runtime/ai_chart_analysis_quality_v2"
)

$ErrorActionPreference = "Stop"
$python = Join-Path $Repository ".venv\Scripts\python.exe"
$outputRootPath = Join-Path $Repository $OutputRoot
$summaryPath = Join-Path $outputRootPath "analytics_summary.json"

if (-not (Test-Path -LiteralPath $python)) {
    throw "AAQTS Python was not found: $python"
}

Set-Location $Repository
$env:AAQTS_AI_CHART_OUTPUT_ROOT = $OutputRoot

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
Write-Host "Dataset: $OutputRoot"
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

function Show-BucketSection {
    param(
        [string]$Title,
        [object]$Section,
        [string]$NameColumn
    )
    Write-Host $Title
    $rows = foreach ($property in $Section.PSObject.Properties) {
        $b = $property.Value
        [PSCustomObject]@{
            Name = $property.Name
            Captures = $b.captures
            Pending = $b.pending
            Finalized = $b.final.samples
            ExpectancyR = $b.final.expectancy_r
            ProfitFactor = $b.final.profit_factor
            Guardrail = if ($b.sample_guardrail_met) { "READY" } else { "NOT_READY" }
        }
    }
    if ($rows) {
        $rows | Sort-Object Name | Format-Table -Property @{Label=$NameColumn;Expression={$_.Name}},Captures,Pending,Finalized,ExpectancyR,ProfitFactor,Guardrail -AutoSize
    } else {
        Write-Host "No data"
    }
}

Show-BucketSection -Title "BY SYMBOL" -Section $s.by_symbol -NameColumn "Symbol"
Show-BucketSection -Title "BY SIGNAL" -Section $s.by_signal -NameColumn "Signal"
Show-BucketSection -Title "BY CONFIDENCE" -Section $s.by_confidence -NameColumn "Confidence"
Show-BucketSection -Title "BY REGIME" -Section $s.by_regime -NameColumn "Regime"
Show-BucketSection -Title "BY STRATEGY" -Section $s.by_strategy -NameColumn "Strategy"

Write-Host "AI COMPARISON"
[PSCustomObject]@{
    Analyzed = $s.ai_comparison.analyzed
    NotAnalyzed = $s.ai_comparison.not_analyzed
} | Format-List
if ($s.ai_comparison.analyzed -gt 0) {
    Show-BucketSection -Title "AAQTS vs AI" -Section $s.ai_comparison.by_relation -NameColumn "Relation"
} else {
    Write-Host "No AI analyses yet; capture-only mode remains active."
}

Write-Host ""
Write-Host $s.readiness.warning
