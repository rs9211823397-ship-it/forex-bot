"""Append-only broker fill evidence used for slippage calibration."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path


class FillAudit:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def append(self, record) -> None:
        encoded = json.dumps(dict(record), sort_keys=True, separators=(",", ":")) + "\n"
        with self._lock, self.path.open("a", encoding="utf-8") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
