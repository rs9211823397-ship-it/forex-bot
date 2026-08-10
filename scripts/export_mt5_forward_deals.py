"""Export closed AAQTS MT5 deals for independent forward-test reporting."""

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd


AAQTS_MAGIC = 20260730


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--terminal", required=True)
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--magic", type=int, default=AAQTS_MAGIC)
    parser.add_argument("--output", default="outputs/validation/mt5_demo_deals.csv")
    args = parser.parse_args()

    if args.days < 1:
        raise ValueError("days must be positive")

    import MetaTrader5 as mt5

    if not mt5.initialize(path=args.terminal, timeout=60000):
        raise RuntimeError(f"MT5 initialization failed: {mt5.last_error()}")
    try:
        now = datetime.now(timezone.utc)
        deals = mt5.history_deals_get(now - timedelta(days=args.days), now) or ()
        rows = []
        for deal in deals:
            if int(getattr(deal, "magic", 0)) != args.magic:
                continue
            if int(getattr(deal, "entry", -1)) not in {
                int(mt5.DEAL_ENTRY_OUT),
                int(mt5.DEAL_ENTRY_OUT_BY),
            }:
                continue
            net_profit = sum(
                float(getattr(deal, field, 0.0) or 0.0)
                for field in ("profit", "commission", "swap", "fee")
            )
            rows.append({
                "timestamp": datetime.fromtimestamp(
                    int(deal.time), tz=timezone.utc
                ).isoformat(),
                "symbol": str(deal.symbol),
                "profit": net_profit,
                "position_id": int(deal.position_id),
                "deal_ticket": int(deal.ticket),
            })
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(
            rows,
            columns=(
                "timestamp",
                "symbol",
                "profit",
                "position_id",
                "deal_ticket",
            ),
        ).to_csv(output, index=False)
        print(f"Exported {len(rows)} closed AAQTS deal(s) to {output}")
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    main()
