"""Build a backtest-assumed versus MT5-observed slippage report."""

import argparse
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from validation.slippage import slippage_report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fills", required=True)
    parser.add_argument("--min-fills", type=int, default=20)
    parser.add_argument("--min-symbol-fills", type=int, default=3)
    parser.add_argument("--max-p95-assumption-ratio", type=float, default=1.0)
    parser.add_argument("--expected-symbols", default="")
    parser.add_argument("--output", default="outputs/validation/slippage.json")
    args = parser.parse_args()
    report = slippage_report(
        args.fills,
        min_fills=args.min_fills,
        min_symbol_fills=args.min_symbol_fills,
        max_p95_assumption_ratio=args.max_p95_assumption_ratio,
        expected_symbols=[item for item in args.expected_symbols.split(",") if item.strip()] or None,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    if not report["sample_complete"] or not report["within_assumption"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
