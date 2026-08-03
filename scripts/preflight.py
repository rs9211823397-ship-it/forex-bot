#!/usr/bin/env python3
"""Release preflight checks for the forex-bot repository."""

import importlib
import os
import subprocess
import sys
from pathlib import Path


REQUIRED_PACKAGES = {
    "numpy": "numpy",
    "pandas": "pandas",
    "yfinance": "yfinance",
    "dotenv": "python-dotenv",
}

OPTIONAL_PACKAGES = {
    "telegram": "python-telegram-bot",
    "MetaTrader5": "MetaTrader5 (Windows only)",
}


def fail(message: str) -> None:
    print(f"[preflight] ERROR: {message}")
    raise SystemExit(1)


def check_python_version() -> None:
    if sys.version_info < (3, 10):
        fail("Python 3.10+ is required")
    print(f"[preflight] Python {sys.version.split()[0]} OK")


def check_repo_root() -> Path:
    repo_root = Path(__file__).resolve().parents[1]
    if not (repo_root / "requirements.txt").exists():
        fail("Repository root could not be determined")
    os.chdir(repo_root)
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    print(f"[preflight] Repository root: {repo_root}")
    return repo_root


def check_required_packages() -> None:
    missing = []
    for module_name, package_name in REQUIRED_PACKAGES.items():
        try:
            importlib.import_module(module_name)
        except Exception:
            missing.append(package_name)

    if missing:
        fail("Missing required packages: " + ", ".join(sorted(missing)))

    print("[preflight] Required packages OK")


def check_optional_packages() -> None:
    missing = []
    for module_name, package_name in OPTIONAL_PACKAGES.items():
        try:
            importlib.import_module(module_name)
        except Exception:
            missing.append(package_name)

    if missing:
        print(f"[preflight] Optional packages not installed: {', '.join(sorted(missing))}")
    else:
        print("[preflight] Optional packages OK")


def check_output_folders(repo_root: Path) -> None:
    required_dirs = [repo_root / "logs", repo_root / "outputs"]
    for directory in required_dirs:
        directory.mkdir(exist_ok=True)
        if not directory.is_dir() or not os.access(directory, os.W_OK):
            fail(f"Output folder is not writable: {directory}")
    print("[preflight] Output folders OK")


def check_execution_mode() -> None:
    from config.settings import EXECUTION_MODE

    if EXECUTION_MODE not in {"PAPER", "MT5_DEMO", "MT5_LIVE"}:
        fail(f"Unsupported AAQTS_EXECUTION_MODE: {EXECUTION_MODE}")
    if EXECUTION_MODE == "MT5_LIVE":
        fail("MT5_LIVE remains locked; use PAPER or MT5_DEMO")
    print(f"[preflight] Execution mode {EXECUTION_MODE} OK")


def check_news_calendar() -> None:
    from config.settings import NEWS_CALENDAR_FILE, NEWS_FILTER_ENABLED

    if not NEWS_FILTER_ENABLED:
        print("[preflight] News filter disabled")
        return
    if not NEWS_CALENDAR_FILE:
        fail(
            "AAQTS_NEWS_CALENDAR_FILE is required when the news filter is enabled"
        )
    from risk.news_calendar import JsonNewsEventProvider

    provider = JsonNewsEventProvider(NEWS_CALENDAR_FILE)
    print(
        f"[preflight] News calendar OK ({len(provider.events)} events)"
    )


def main() -> None:
    check_python_version()
    repo_root = check_repo_root()
    check_required_packages()
    check_optional_packages()
    check_output_folders(repo_root)
    check_execution_mode()
    check_news_calendar()
    print("[preflight] Preflight passed")


if __name__ == "__main__":
    main()
