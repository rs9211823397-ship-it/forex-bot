from pathlib import Path


def test_demo_profile_uses_only_utbot_indicator_policy():
    root = Path(__file__).resolve().parents[1]
    launcher = (root / "scripts" / "windows" / "start-demo-engine.ps1").read_text(
        encoding="utf-8"
    )

    assert 'AAQTS_STRATEGY_MODE = "UT_BOT"' in launcher
    assert 'AAQTS_UTBOT_KEY_VALUE = "3.0"' in launcher
    assert 'AAQTS_UTBOT_ATR_PERIOD = "10"' in launcher
    assert "AAQTS_UTBOT_EMA_PERIOD" not in launcher
    assert 'AAQTS_UTBOT_SIGNAL_CONFIDENCE = "80"' in launcher
    assert 'AAQTS_UTBOT_EXIT_MODE = "ATR_TRAIL"' in launcher
    assert 'AAQTS_UTBOT_INITIAL_SL_ATR_MULTIPLIER = "1.5"' in launcher
    assert 'AAQTS_UTBOT_BREAK_EVEN_TRIGGER_R = "1.0"' in launcher
    assert 'AAQTS_UTBOT_TRAILING_START_R = "1.5"' in launcher
    assert 'AAQTS_UTBOT_TRAILING_ATR_MULTIPLIER = "2.5"' in launcher
    assert 'AAQTS_RISK_PERCENT = "0.5"' in launcher
    assert 'AAQTS_MT5_MAX_OPEN_POSITIONS = "3"' in launcher
    assert 'AAQTS_MAX_CONSECUTIVE_LOSSES = "0"' in launcher
    assert 'AAQTS_MAX_DAILY_TRADES = "0"' in launcher
    assert 'AAQTS_MT5_STOP_LOSS_COOLDOWN_MINUTES = "0"' in launcher

    assert "AAQTS_MIN_ADX =" not in launcher
    assert "AAQTS_SIGNAL_SCORE_THRESHOLD =" not in launcher
    assert "AAQTS_MIN_SIGNAL_CONFIRMATIONS =" not in launcher
    assert "AAQTS_MIN_TRADE_QUALITY =" not in launcher
    assert "AAQTS_MIN_REGIME_CONFIDENCE =" not in launcher
    assert "AAQTS_PORTFOLIO_MAX_ABS_CORRELATION =" not in launcher
    assert "AAQTS_PORTFOLIO_MAX_CORRELATED_RISK_PERCENT =" not in launcher


def test_quality_v3_balanced_research_cohort_is_isolated_across_runtime_tools():
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

    cohort = "runtime/ai_chart_analysis_utbot"
    assert f'AAQTS_AI_CHART_OUTPUT_ROOT = "{cohort}"' in engine
    assert f'AAQTS_AI_CHART_OUTPUT_ROOT = "{cohort}"' in watcher
    assert f'[string]$OutputRoot = "{cohort}"' in analytics
    assert "Dataset: $OutputRoot" in analytics


def test_utbot_protected_lifecycle_disables_remote_ai_but_keeps_news_veto():
    root = Path(__file__).resolve().parents[1]
    launcher = (root / "scripts" / "windows" / "start-demo-engine.ps1").read_text(
        encoding="utf-8"
    )

    assert 'AAQTS_AI_CHART_REMOTE_ENABLED = "false"' in launcher
    assert "Remove-Item Env:OPENAI_API_KEY" in launcher
    assert 'AAQTS_NEWS_FILTER_ENABLED = "true"' in launcher


def test_quality_v3_balanced_writes_non_secret_runtime_profile_manifest():
    root = Path(__file__).resolve().parents[1]
    launcher = (root / "scripts" / "windows" / "start-demo-engine.ps1").read_text(
        encoding="utf-8"
    )

    assert 'utbot_runtime_profile.json' in launcher
    assert '$runtimeProfile = [ordered]@{' in launcher
    assert 'profile = "utbot_atr_trail_v1"' in launcher
    assert 'strategy_mode = $env:AAQTS_STRATEGY_MODE' in launcher
    assert 'utbot_key_value = [double]$env:AAQTS_UTBOT_KEY_VALUE' in launcher
    assert 'utbot_atr_period = [int]$env:AAQTS_UTBOT_ATR_PERIOD' in launcher
    assert 'utbot_ema_period' not in launcher
    assert 'exit_mode = $env:AAQTS_UTBOT_EXIT_MODE' in launcher
    assert 'initial_sl_atr = [double]$env:AAQTS_UTBOT_INITIAL_SL_ATR_MULTIPLIER' in launcher
    assert 'trailing_atr = [double]$env:AAQTS_UTBOT_TRAILING_ATR_MULTIPLIER' in launcher
    assert 'Set-Content -LiteralPath $profileFile -Encoding UTF8' in launcher

    profile_block = launcher.split('$runtimeProfile = [ordered]@{', 1)[1].split(
        '$runtimeProfile | ConvertTo-Json', 1
    )[0]
    assert 'AAQTS_MT5_PASSWORD' not in profile_block
    assert 'TELEGRAM_BOT_TOKEN' not in profile_block
    assert 'OPENAI_API_KEY' not in profile_block
