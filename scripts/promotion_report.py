"""Combine backtest, TradingView parity, and demo-forward evidence."""

import argparse
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from validation.workflow import promotion_report


def _load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backtest", required=True)
    parser.add_argument("--parity", required=True)
    parser.add_argument("--forward", required=True)
    parser.add_argument("--output", default="outputs/validation/promotion.json")
    parser.add_argument("--min-backtest-trades", type=int, default=100)
    parser.add_argument("--min-oos-trades", type=int, default=20)
    parser.add_argument("--min-profit-factor", type=float, default=1.2)
    parser.add_argument("--max-drawdown-percent", type=float, default=10.0)
    parser.add_argument("--min-parity-percent", type=float, default=99.0)
    args = parser.parse_args()

    report = promotion_report(
        backtest_metrics=_load(args.backtest),
        parity_metrics=_load(args.parity),
        forward_metrics=_load(args.forward),
        min_backtest_trades=args.min_backtest_trades,
        min_out_of_sample_trades=args.min_oos_trades,
        min_profit_factor=args.min_profit_factor,
        max_drawdown_percent=args.max_drawdown_percent,
        min_parity_percent=args.min_parity_percent,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))

    if not report["eligible_for_human_review"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
