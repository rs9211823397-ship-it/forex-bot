"""AAQTS Phase AI-1 chart-analysis observer.

This package is intentionally isolated from execution. Observer outputs are
evidence records only; they cannot place, size, modify, or close positions.
"""

from .config import ChartObserverConfig
from .schema import ANALYSIS_JSON_SCHEMA, ChartAnalysis
from .snapshot import MarketSnapshot, build_market_snapshot

__all__ = [
    "ANALYSIS_JSON_SCHEMA",
    "ChartAnalysis",
    "ChartObserverConfig",
    "MarketSnapshot",
    "build_market_snapshot",
]
