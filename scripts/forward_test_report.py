"""Build a deterministic report from an MT5 AAQTS closed-deal export."""

import argparse
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from validation.workflow import forward_test_report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--deals", required=True)
    parser.add_argument("--min-trades", type=int, default=100)
    parser.add_argument("--min-symbol-trades", type=int, default=10)
    parser.add_argument(
        "--expected-symbols",
        default="",
        help="Comma-separated broker symbols that must each meet the per-symbol sample",
    )
    parser.add_argument(
        "--starting-equity",
        type=float,
        required=True,
        help="AAQTS forward-test equity at the configured risk baseline",
    )
    parser.add_argument("--output", default="outputs/validation/forward_test.json")
    args = parser.parse_args()
    report = forward_test_report(
        args.deals,
        min_closed_trades=args.min_trades,
        starting_equity=args.starting_equity,
        min_symbol_trades=args.min_symbol_trades,
        expected_symbols=[item for item in args.expected_symbols.split(",") if item.strip()] or None,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
