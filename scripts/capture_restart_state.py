"""Capture broker/runtime identity and managed positions for restart testing."""

import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--terminal", required=True)
    parser.add_argument("--status", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--magic", type=int, default=20260730)
    args = parser.parse_args()

    import MetaTrader5 as mt5
    if not mt5.initialize(path=args.terminal, timeout=60000):
        raise RuntimeError(f"MT5 initialization failed: {mt5.last_error()}")
    try:
        runtime = json.loads(Path(args.status).read_text(encoding="utf-8"))
        positions = mt5.positions_get()
        if positions is None:
            raise RuntimeError(f"MT5 positions unavailable: {mt5.last_error()}")
        managed = []
        for item in positions:
            if int(getattr(item, "magic", 0)) != args.magic:
                continue
            managed.append({
                "ticket": int(item.ticket),
                "symbol": str(item.symbol),
                "side": "BUY" if int(item.type) == int(mt5.POSITION_TYPE_BUY) else "SELL",
                "volume": float(item.volume),
                "price_open": float(item.price_open),
                "sl": float(item.sl),
                "tp": float(item.tp),
            })
        payload = {"runtime": runtime, "positions": sorted(managed, key=lambda item: item["ticket"])}
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        print(output)
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    main()
