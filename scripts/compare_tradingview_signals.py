"""Compare exported AAQTS and TradingView close-confirmed signals."""

import argparse
import json
from pathlib import Path

from validation.workflow import compare_signal_ledgers


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--aaqts", required=True)
    parser.add_argument("--tradingview", required=True)
    parser.add_argument("--output", default="outputs/validation/tradingview_parity.json")
    args = parser.parse_args()
    report = compare_signal_ledgers(args.aaqts, args.tradingview)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
