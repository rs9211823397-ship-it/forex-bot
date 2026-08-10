"""Configuration-level MT5 authentication policy tests."""

from __future__ import annotations

import os
import subprocess
import sys


def _settings_probe(overrides: dict[str, str]) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.update(overrides)
    return subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from config.settings import MT5_LOGIN,MT5_PASSWORD,MT5_SERVER; "
                "print(repr((MT5_LOGIN,MT5_PASSWORD,MT5_SERVER)))"
            ),
        ],
        cwd=os.path.dirname(os.path.dirname(__file__)),
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def test_demo_preauthenticated_mode_ignores_stale_dotenv_credentials():
    result = _settings_probe(
        {
            "AAQTS_EXECUTION_MODE": "MT5_DEMO",
            "AAQTS_MT5_USE_PREAUTHENTICATED_SESSION": "true",
            "AAQTS_MT5_LOGIN": "12345678",
            "AAQTS_MT5_PASSWORD": "stale-secret",
            "AAQTS_MT5_SERVER": "Stale-Server",
        }
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "('', '', '')"


def test_live_mode_rejects_preauthenticated_session():
    result = _settings_probe(
        {
            "AAQTS_EXECUTION_MODE": "MT5_LIVE",
            "AAQTS_MT5_USE_PREAUTHENTICATED_SESSION": "true",
        }
    )

    assert result.returncode != 0
    assert "not allowed in MT5_LIVE" in result.stderr
