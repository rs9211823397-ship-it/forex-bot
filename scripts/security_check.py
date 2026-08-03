#!/usr/bin/env python3
"""Fail when source files contain obvious credentials or tracked runtime data."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TELEGRAM_TOKEN = re.compile(r"\b\d{8,12}:[A-Za-z0-9_-]{30,}\b")
RUNTIME_PATTERNS = (
    "__pycache__/",
    ".pyc",
    "trades.json",
    "account.json",
    " phone",
    "backup.py",
    ".backup",
)


def tracked_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def main() -> None:
    failures = []
    for relative in tracked_files():
        lowered = relative.lower()
        if any(pattern in lowered for pattern in RUNTIME_PATTERNS):
            failures.append(f"tracked runtime/backup artifact: {relative}")
        path = ROOT / relative
        if not path.is_file() or path.suffix.lower() not in {
            ".py", ".md", ".txt", ".json", ".yml", ".yaml", ".env"
        }:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if TELEGRAM_TOKEN.search(content):
            failures.append(f"Telegram token-shaped credential: {relative}")

    if failures:
        raise SystemExit("\n".join(f"[security] {item}" for item in failures))
    print("[security] source and tracked-artifact checks passed")


if __name__ == "__main__":
    main()
