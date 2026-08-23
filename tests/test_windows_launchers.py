from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
WINDOWS = ROOT / "scripts" / "windows"


def test_demo_launcher_has_one_canonical_assignment_per_policy_key():
    text = (WINDOWS / "start-demo-engine.ps1").read_text(encoding="utf-8")
    keys = (
        "AAQTS_MT5_MAX_SPREAD_STOP_RATIO",
        "AAQTS_STRATEGY_MODE",
        "AAQTS_UTBOT_KEY_VALUE",
        "AAQTS_UTBOT_ATR_PERIOD",
        "AAQTS_UTBOT_EXIT_MODE",
        "AAQTS_UTBOT_INITIAL_SL_ATR_MULTIPLIER",
        "AAQTS_UTBOT_BREAK_EVEN_TRIGGER_R",
        "AAQTS_UTBOT_TRAILING_START_R",
        "AAQTS_UTBOT_TRAILING_ATR_MULTIPLIER",
    )

    for key in keys:
        assert text.count(f"$env:{key} =") == 1

    assert '$env:AAQTS_MT5_MAX_SPREAD_STOP_RATIO = "0.35"' in text
    assert '$env:AAQTS_BOT_INTERVAL_SECONDS = "1"' in text
    assert '$env:AAQTS_MT5_MAX_OPEN_POSITIONS = "3"' in text


def test_windows_launchers_contain_no_plaintext_telegram_token():
    combined = "\n".join(
        path.read_text(encoding="utf-8")
        for path in WINDOWS.glob("*.ps1")
    )

    assert re.search(r"\d{6,12}:[A-Za-z0-9_-]{30,}", combined) is None
    assert "ConvertFrom-SecureString" in combined
    assert "mt5_demo_password.dpapi" in combined
    assert "telegram_token.dpapi" in combined


def test_demo_launcher_explicitly_overrides_stale_dotenv_credentials():
    text = (WINDOWS / "start-demo-engine.ps1").read_text(encoding="utf-8")

    assert 'AAQTS_MT5_USE_PREAUTHENTICATED_SESSION = "true"' in text
    assert 'AAQTS_MT5_USE_PREAUTHENTICATED_SESSION = "false"' in text
    assert 'AAQTS_MT5_LOGIN = ""' in text
    assert 'AAQTS_MT5_PASSWORD = ""' in text
    assert 'AAQTS_MT5_SERVER = ""' in text


def test_telegram_launcher_uses_normal_manager_not_temporary_indicator_overlay():
    text = (WINDOWS / "start-telegram.ps1").read_text(encoding="utf-8")

    assert 'AAQTS_STRATEGY_MODE = "UT_BOT"' in text
    assert "-m telegram_bot.bot" in text
    assert "native_24h_entry" not in text


def test_winprofx_secret_files_are_written_without_trailing_newlines():
    text = (WINDOWS / "save-winprofx-live-credentials.ps1").read_text(encoding="utf-8")

    assert text.count("-NoNewline") == 3
    assert "winprofx_live_password.dpapi" in text


def test_winprofx_launchers_trim_dpapi_ciphertext_before_decryption():
    engine = (WINDOWS / "start-winprofx-live-engine.ps1").read_text(encoding="utf-8")
    telegram = (WINDOWS / "start-winprofx-live-telegram.ps1").read_text(encoding="utf-8")

    assert "ReadAllText($passwordFile).Trim()" in engine
    assert "ReadAllText($passwordFile).Trim()" in telegram
    assert "ReadAllText($tokenFile).Trim()" in telegram


def test_winprofx_launcher_supports_non_trading_preflight_only_mode():
    text = (WINDOWS / "start-winprofx-live-engine.ps1").read_text(encoding="utf-8")

    assert "[switch]$PreflightOnly" in text
    assert "WINPROFX_LIVE_PREFLIGHT_PASSED" in text
    assert text.index("if ($PreflightOnly)") < text.index("& $python main.py")
