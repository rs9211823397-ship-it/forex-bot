from pathlib import Path
import subprocess
import sys

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "script",
    (
        "scripts/compare_tradingview_signals.py",
        "scripts/forward_test_report.py",
        "scripts/promotion_report.py",
    ),
)
def test_validation_scripts_are_directly_runnable(script):
    result = subprocess.run(
        [sys.executable, script, "--help"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout.lower()
