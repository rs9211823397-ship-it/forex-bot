"""Build a deterministic report from an MT5 AAQTS closed-deal export."""

import argparse
import json
from pathlib import Path

from validation.workflow import forward_test_report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--deals", required=True)
    parser.add_argument("--min-trades", type=int, default=100)
    parser.add_argument("--output", default="outputs/validation/forward_test.json")
    args = parser.parse_args()
    report = forward_test_report(args.deals, min_closed_trades=args.min_trades)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
