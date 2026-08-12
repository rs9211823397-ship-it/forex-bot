from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
WINDOWS = ROOT / "scripts" / "windows"


def test_demo_launcher_has_one_canonical_assignment_per_policy_key():
    text = (WINDOWS / "start-demo-engine.ps1").read_text(encoding="utf-8")
    keys = (
        "AAQTS_MT5_MAX_OPEN_POSITIONS",
        "AAQTS_MT5_MAX_SPREAD_STOP_RATIO",
        "AAQTS_MIN_ADX",
        "AAQTS_SIGNAL_SCORE_THRESHOLD",
        "AAQTS_MIN_SIGNAL_CONFIRMATIONS",
        "AAQTS_MIN_TRADE_QUALITY",
        "AAQTS_MIN_REGIME_CONFIDENCE",
    )

    for key in keys:
        assert text.count(f"$env:{key} =") == 1

    assert '$env:AAQTS_MT5_MAX_SPREAD_STOP_RATIO = "0.35"' in text


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
