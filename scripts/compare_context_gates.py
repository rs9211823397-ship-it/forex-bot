"""Compare production Python-only gates with an independent raw-candle reference."""

import argparse
import json
from pathlib import Path
import sys

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from validation.context_parity import (
    compare_context_snapshots,
    independent_context_snapshot,
    production_context_snapshot,
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--lower", required=True, help="Lower-timeframe OHLC CSV")
    parser.add_argument("--higher", required=True, help="Higher-timeframe OHLC CSV")
    parser.add_argument("--decision-time", required=True)
    parser.add_argument("--direction", required=True, choices=("BUY", "SELL"))
    parser.add_argument("--lower-timeframe", default="15m")
    parser.add_argument("--higher-timeframe", default="1h")
    parser.add_argument("--output", default="outputs/validation/context_parity.json")
    args = parser.parse_args()

    lower = pd.read_csv(args.lower)
    higher = pd.read_csv(args.higher)
    production = production_context_snapshot(
        lower,
        higher,
        decision_time=args.decision_time,
        direction=args.direction,
        lower_timeframe=args.lower_timeframe,
        higher_timeframe=args.higher_timeframe,
    )
    independent = independent_context_snapshot(
        lower,
        higher,
        decision_time=args.decision_time,
        direction=args.direction,
    )
    report = compare_context_snapshots(production, independent)
    report.update({"production": production, "independent": independent})
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    if not report["passed"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
