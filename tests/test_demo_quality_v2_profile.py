from pathlib import Path


def test_demo_quality_v2_profile_is_stricter_and_keeps_size_constant():
    root = Path(__file__).resolve().parents[1]
    launcher = (root / "scripts" / "windows" / "start-demo-engine.ps1").read_text(
        encoding="utf-8"
    )

    assert 'AAQTS_MT5_FIXED_LOT = "0.05"' in launcher
    assert 'AAQTS_RISK_PERCENT = "1.0"' in launcher
    assert 'AAQTS_MT5_MAX_OPEN_POSITIONS = "3"' in launcher
    assert 'AAQTS_MAX_CONSECUTIVE_LOSSES = "3"' in launcher
    assert 'AAQTS_MAX_DAILY_TRADES = "8"' in launcher
    assert 'AAQTS_MT5_STOP_LOSS_COOLDOWN_MINUTES = "30"' in launcher

    assert 'AAQTS_MIN_ADX = "18"' in launcher
    assert 'AAQTS_SIGNAL_SCORE_THRESHOLD = "50"' in launcher
    assert 'AAQTS_MIN_SIGNAL_CONFIRMATIONS = "2"' in launcher
    assert 'AAQTS_MIN_TRADE_QUALITY = "50"' in launcher
    assert 'AAQTS_MIN_REGIME_CONFIDENCE = "45"' in launcher
    assert 'AAQTS_PORTFOLIO_MAX_ABS_CORRELATION = "0.85"' in launcher
    assert 'AAQTS_PORTFOLIO_MAX_CORRELATED_RISK_PERCENT = "4.0"' in launcher


def test_quality_v2_research_cohort_is_isolated_across_runtime_tools():
    root = Path(__file__).resolve().parents[1]
    engine = (root / "scripts" / "windows" / "start-demo-engine.ps1").read_text(
        encoding="utf-8"
    )
    watcher = (
        root / "scripts" / "windows" / "start-ai-research-watcher.ps1"
    ).read_text(encoding="utf-8")
    analytics = (
        root / "scripts" / "windows" / "show-ai-chart-analytics.ps1"
    ).read_text(encoding="utf-8")

    cohort = "runtime/ai_chart_analysis_quality_v2"
    assert f'AAQTS_AI_CHART_OUTPUT_ROOT = "{cohort}"' in engine
    assert f'AAQTS_AI_CHART_OUTPUT_ROOT = "{cohort}"' in watcher
    assert f'[string]$OutputRoot = "{cohort}"' in analytics
    assert "Dataset: $OutputRoot" in analytics


def test_quality_v2_does_not_enable_remote_ai_or_disable_news_filter():
    root = Path(__file__).resolve().parents[1]
    launcher = (root / "scripts" / "windows" / "start-demo-engine.ps1").read_text(
        encoding="utf-8"
    )

    assert 'AAQTS_AI_CHART_REMOTE_ENABLED = "false"' in launcher
    assert "Remove-Item Env:OPENAI_API_KEY" in launcher
    assert 'AAQTS_NEWS_FILTER_ENABLED = "true"' in launcher


def test_quality_v2_writes_non_secret_runtime_profile_manifest():
    root = Path(__file__).resolve().parents[1]
    launcher = (root / "scripts" / "windows" / "start-demo-engine.ps1").read_text(
        encoding="utf-8"
    )

    assert 'quality_v2_runtime_profile.json' in launcher
    assert '$runtimeProfile = [ordered]@{' in launcher
    assert 'profile = "quality_v2"' in launcher
    assert 'min_adx = [double]$env:AAQTS_MIN_ADX' in launcher
    assert 'signal_score_threshold = [int]$env:AAQTS_SIGNAL_SCORE_THRESHOLD' in launcher
    assert 'min_signal_confirmations = [int]$env:AAQTS_MIN_SIGNAL_CONFIRMATIONS' in launcher
    assert 'min_trade_quality = [int]$env:AAQTS_MIN_TRADE_QUALITY' in launcher
    assert 'Set-Content -LiteralPath $profileFile -Encoding UTF8' in launcher

    profile_block = launcher.split('$runtimeProfile = [ordered]@{', 1)[1].split(
        '$runtimeProfile | ConvertTo-Json', 1
    )[0]
    assert 'AAQTS_MT5_PASSWORD' not in profile_block
    assert 'TELEGRAM_BOT_TOKEN' not in profile_block
    assert 'OPENAI_API_KEY' not in profile_block
