#!/usr/bin/env python3
"""Compare UT Bot + EMA200 with daily VWAP + EMA9 on one candle universe."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtesting.indicator_comparison import (  # noqa: E402
    ComparisonConfig,
    strategy_metrics_with_holdout,
    ut_bot_ema200_events,
    vwap_ema9_events,
)
from config.symbols import (  # noqa: E402
    SYMBOL_CATALOG,
    symbol_by_broker,
    symbol_by_data,
)
from data.market_data import MarketData  # noqa: E402


STRATEGIES = ("UT_BOT_EMA200", "VWAP_EMA9")


def _symbol_universe(raw: str, include_paper_only: bool) -> list[str]:
    requested = [item.strip().upper() for item in str(raw).split(",") if item.strip()]
    if not requested or requested == ["ALL"]:
        symbols = [
            item.data_symbol
            for item in SYMBOL_CATALOG
            if item.data_symbol
            and (
                item.enabled_by_default
                or (include_paper_only and item.entry_policy == "PAPER_ONLY")
            )
        ]
        return list(dict.fromkeys(str(item) for item in symbols))

    resolved: list[str] = []
    for value in requested:
        try:
            definition = symbol_by_broker(value)
        except KeyError:
            definition = symbol_by_data(value)
        if not definition.data_symbol:
            raise ValueError(
                f"{value} has no exact research data mapping: {definition.disabled_reason}"
            )
        resolved.append(definition.data_symbol)
    return list(dict.fromkeys(resolved))


def _load_csv(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    time_column = "open_time" if "open_time" in frame.columns else "timestamp"
    if time_column not in frame.columns:
        raise ValueError(f"{path} requires open_time or timestamp")
    frame["open_time"] = pd.to_datetime(frame[time_column], utc=True, errors="raise")
    frame = frame.set_index("open_time", drop=False)
    return frame


def _safe_symbol(symbol: str) -> str:
    return "".join(character.lower() if character.isalnum() else "_" for character in symbol).strip("_")


def _download_frame(
    symbol: str,
    *,
    provider: str,
    timeframe: str,
    csv_dir: Path | None,
) -> pd.DataFrame:
    if csv_dir is not None:
        candidates = (
            csv_dir / f"{symbol}.csv",
            csv_dir / f"{_safe_symbol(symbol)}.csv",
        )
        for candidate in candidates:
            if candidate.is_file():
                return _load_csv(candidate)
        raise FileNotFoundError(
            f"No CSV for {symbol}; expected {candidates[0]} or {candidates[1]}"
        )

    if provider == "MT5":
        market = MarketData(
            # Historical comparison must not fail merely because the newest
            # candle is old during a weekend/market closure.  Provider=MT5
            # still reads the broker terminal; PAPER only disables live-feed
            # freshness enforcement and never sends an order.
            execution_mode="PAPER",
            provider="MT5",
            allow_cache_fallback=False,
            cache_downloads=False,
        )
        return market.download_data(symbol, timeframe, use_cache=False)
    market = MarketData(
        execution_mode="PAPER",
        provider="YAHOO",
        allow_cache_fallback=True,
        cache_downloads=True,
    )
    return market.download_data(symbol, timeframe, use_cache=True)


def _dataset_fingerprint(frame: pd.DataFrame) -> str:
    columns = ["open", "high", "low", "close", "volume"]
    payload = frame[columns].copy()
    if "open_time" in frame.columns:
        timestamps = pd.to_datetime(frame["open_time"], utc=True, errors="raise")
    else:
        timestamps = pd.to_datetime(frame.index, utc=True, errors="raise")
    payload.insert(0, "open_time", pd.DatetimeIndex(timestamps).astype(str))
    hashed = pd.util.hash_pandas_object(payload, index=False).to_numpy().tobytes()
    return hashlib.sha256(hashed).hexdigest()


def _flatten_metrics(
    *,
    symbol: str,
    strategy: str,
    section: str,
    metrics: dict[str, Any],
) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "strategy": strategy,
        "sample": section,
        **metrics,
    }


def _finite_pf(value: object) -> float:
    if value is None:
        return float("inf")
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _winner(
    left: dict[str, Any],
    right: dict[str, Any],
    *,
    min_trades: int,
) -> str:
    if min(int(left["completed_trades"]), int(right["completed_trades"])) < min_trades:
        return "INSUFFICIENT_OOS_SAMPLE"
    left_key = (
        float(left["net_return_percent"]),
        _finite_pf(left["profit_factor"]),
        -float(left["max_drawdown_percent"]),
    )
    right_key = (
        float(right["net_return_percent"]),
        _finite_pf(right["profit_factor"]),
        -float(right["max_drawdown_percent"]),
    )
    if left_key == right_key:
        return "TIE"
    return "UT_BOT_EMA200" if left_key > right_key else "VWAP_EMA9"


def _excluded_catalog() -> list[dict[str, str]]:
    return [
        {
            "broker_symbol": item.broker_symbol,
            "data_symbol": item.data_symbol or "",
            "entry_policy": item.entry_policy,
            "reason": item.disabled_reason,
        }
        for item in SYMBOL_CATALOG
        if not item.enabled_by_default
    ]


def _aggregate_oos(symbols: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    successful = [item for item in symbols if not item.get("error")]
    for strategy in STRATEGIES:
        metrics = [item["strategies"][strategy]["out_of_sample"] for item in successful]
        returns = [float(item["net_return_percent"]) for item in metrics]
        drawdowns = [float(item["max_drawdown_percent"]) for item in metrics]
        result[strategy] = {
            "symbols": len(metrics),
            "total_completed_trades": sum(int(item["completed_trades"]) for item in metrics),
            "profitable_symbols": sum(value > 0 for value in returns),
            "losing_symbols": sum(value < 0 for value in returns),
            "mean_symbol_return_percent": sum(returns) / len(returns) if returns else 0.0,
            "median_symbol_return_percent": float(pd.Series(returns).median()) if returns else 0.0,
            "mean_symbol_max_drawdown_percent": sum(drawdowns) / len(drawdowns) if drawdowns else 0.0,
            "worst_symbol_max_drawdown_percent": max(drawdowns, default=0.0),
        }
    return result


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# UT Bot + EMA200 vs VWAP + EMA9",
        "",
        f"- Timeframe: `{report['settings']['timeframe']}` closed candles",
        f"- Provider: `{report['settings']['provider']}`",
        "- Execution: next-candle open; opposite signal exit/reversal",
        f"- Catastrophe stop: `{report['settings']['catastrophe_stop_percent']}%`",
        f"- Round-trip cost: `{report['settings']['round_trip_cost_bps']} bps`",
        f"- OOS split: `{report['settings']['holdout_percent']}%` chronological tail",
        "- Exposure: one normalized position per symbol; no leverage or MT5 lot sizing",
        "",
        "| Symbol | OOS winner | UT trades | UT return | UT PF | UT DD | VWAP trades | VWAP return | VWAP PF | VWAP DD |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for item in report["symbols"]:
        if item.get("error"):
            lines.append(f"| {item['symbol']} | ERROR | — | — | — | — | — | — | — | — |")
            continue
        ut = item["strategies"]["UT_BOT_EMA200"]["out_of_sample"]
        vw = item["strategies"]["VWAP_EMA9"]["out_of_sample"]
        lines.append(
            "| {symbol} | {winner} | {utn} | {utr:.2f}% | {utpf} | {utdd:.2f}% | "
            "{vwn} | {vwr:.2f}% | {vwpf} | {vwdd:.2f}% |".format(
                symbol=item["symbol"],
                winner=item["oos_winner"],
                utn=ut["completed_trades"],
                utr=ut["net_return_percent"],
                utpf="∞" if ut["profit_factor"] is None else f"{ut['profit_factor']:.2f}",
                utdd=ut["max_drawdown_percent"],
                vwn=vw["completed_trades"],
                vwr=vw["net_return_percent"],
                vwpf="∞" if vw["profit_factor"] is None else f"{vw['profit_factor']:.2f}",
                vwdd=vw["max_drawdown_percent"],
            )
        )
    lines.extend(
        [
            "",
            f"**Overall OOS verdict:** `{report['overall']['verdict']}`",
            f"**Eligible symbol comparisons:** `{report['overall']['eligible_symbol_comparisons']}` / `{report['overall']['successful_symbols']}`",
            "",
            "| Strategy | OOS trades | Profitable symbols | Mean symbol return | Median symbol return | Worst symbol DD |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for strategy in STRATEGIES:
        aggregate = report["overall"]["aggregate_oos"][strategy]
        lines.append(
            "| {strategy} | {trades} | {profitable}/{symbols} | {mean:.2f}% | "
            "{median:.2f}% | {drawdown:.2f}% |".format(
                strategy=strategy,
                trades=aggregate["total_completed_trades"],
                profitable=aggregate["profitable_symbols"],
                symbols=aggregate["symbols"],
                mean=aggregate["mean_symbol_return_percent"],
                median=aggregate["median_symbol_return_percent"],
                drawdown=aggregate["worst_symbol_max_drawdown_percent"],
            )
        )
    lines.extend(
        [
            "",
            "A winner is withheld per symbol when either strategy has fewer than the configured minimum OOS trades. The overall verdict is the majority of eligible symbol winners; aggregate statistics remain visible to challenge that verdict. This is research evidence, not permission to enable live execution.",
        ]
    )
    return "\n".join(lines) + "\n"


def run(args: argparse.Namespace) -> dict[str, Any]:
    symbols = _symbol_universe(args.symbols, args.include_paper_only)
    config = ComparisonConfig(
        initial_equity=args.initial_equity,
        catastrophe_stop_percent=args.stop_percent,
        round_trip_cost_bps=args.cost_bps,
    )
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_dir = Path(args.csv_dir) if args.csv_dir else None
    report: dict[str, Any] = {
        "settings": {
            "provider": "CSV" if csv_dir else args.provider,
            "timeframe": args.timeframe,
            "lookback_bars": args.lookback_bars,
            "initial_equity": args.initial_equity,
            "catastrophe_stop_percent": args.stop_percent,
            "round_trip_cost_bps": args.cost_bps,
            "holdout_percent": args.holdout_percent,
            "minimum_oos_trades": args.min_oos_trades,
            "max_drawdown_basis": "TRADE_CLOSE_EQUITY",
            "ut_bot": {"key_value": args.ut_key, "atr_period": args.ut_atr, "ema_period": 200},
            "vwap_ema": {"vwap_anchor": "UTC_DAY", "ema_period": 9},
        },
        "requested_symbols": symbols,
        "excluded_catalog_symbols": _excluded_catalog(),
        "symbols": [],
    }
    metric_rows: list[dict[str, Any]] = []
    trade_rows: list[dict[str, Any]] = []
    wins = {"UT_BOT_EMA200": 0, "VWAP_EMA9": 0, "TIE": 0, "INSUFFICIENT_OOS_SAMPLE": 0}

    for symbol in symbols:
        item: dict[str, Any] = {"symbol": symbol}
        try:
            frame = _download_frame(
                symbol,
                provider=args.provider,
                timeframe=args.timeframe,
                csv_dir=csv_dir,
            ).tail(args.lookback_bars).copy()
            ut_events, _ = ut_bot_ema200_events(
                frame,
                key_value=args.ut_key,
                atr_period=args.ut_atr,
                ema_period=200,
            )
            vwap_events, _ = vwap_ema9_events(frame, ema_period=9)
            strategies: dict[str, Any] = {}
            for name, events in (
                ("UT_BOT_EMA200", ut_events),
                ("VWAP_EMA9", vwap_events),
            ):
                trades, metrics = strategy_metrics_with_holdout(
                    frame,
                    events,
                    strategy_name=name,
                    symbol=symbol,
                    config=config,
                    holdout_fraction=args.holdout_percent / 100.0,
                )
                strategies[name] = metrics
                trade_rows.extend(trades)
                metric_rows.append(
                    _flatten_metrics(symbol=symbol, strategy=name, section="FULL", metrics=metrics["full"])
                )
                metric_rows.append(
                    _flatten_metrics(symbol=symbol, strategy=name, section="OOS", metrics=metrics["out_of_sample"])
                )
            winner = _winner(
                strategies["UT_BOT_EMA200"]["out_of_sample"],
                strategies["VWAP_EMA9"]["out_of_sample"],
                min_trades=args.min_oos_trades,
            )
            wins[winner] += 1
            item.update(
                {
                    "candles": len(frame),
                    "dataset_sha256": _dataset_fingerprint(frame),
                    "data_source": str(frame.attrs.get("source", "CSV" if csv_dir else args.provider)),
                    "broker_symbol": str(frame.attrs.get("broker_symbol", "")),
                    "start": pd.Timestamp(frame["open_time"].iloc[0] if "open_time" in frame.columns else frame.index[0]).isoformat(),
                    "end": pd.Timestamp(frame["close_time"].iloc[-1] if "close_time" in frame.columns else frame.index[-1]).isoformat(),
                    "oos_winner": winner,
                    "strategies": strategies,
                }
            )
        except Exception as exc:  # continue so coverage gaps remain visible
            item["error"] = f"{type(exc).__name__}: {exc}"
        report["symbols"].append(item)

    eligible = wins["UT_BOT_EMA200"] + wins["VWAP_EMA9"] + wins["TIE"]
    if eligible == 0:
        verdict = "INSUFFICIENT_EVIDENCE"
    elif wins["UT_BOT_EMA200"] == wins["VWAP_EMA9"]:
        verdict = "TIE"
    elif wins["UT_BOT_EMA200"] > wins["VWAP_EMA9"]:
        verdict = "UT_BOT_EMA200"
    else:
        verdict = "VWAP_EMA9"
    errors = [item for item in report["symbols"] if item.get("error")]
    report["overall"] = {
        "verdict": verdict,
        "symbol_wins": wins,
        "eligible_symbol_comparisons": eligible,
        "successful_symbols": len(report["symbols"]) - len(errors),
        "failed_symbols": len(errors),
        "complete_coverage": not errors,
        "aggregate_oos": _aggregate_oos(report["symbols"]),
    }

    (output_dir / "utbot_vwap_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    pd.DataFrame(metric_rows).to_csv(output_dir / "utbot_vwap_metrics.csv", index=False)
    pd.DataFrame(trade_rows).to_csv(output_dir / "utbot_vwap_trades.csv", index=False)
    (output_dir / "utbot_vwap_report.md").write_text(_markdown(report), encoding="utf-8")
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", default="ALL", help="ALL or comma-separated broker/data symbols")
    parser.add_argument("--provider", choices=("MT5", "YAHOO"), default=os.getenv("AAQTS_COMPARISON_PROVIDER", "MT5").upper())
    parser.add_argument("--csv-dir", default="", help="Optional directory containing one OHLCV CSV per symbol")
    parser.add_argument("--timeframe", default="15m")
    parser.add_argument("--lookback-bars", type=int, default=6_000)
    parser.add_argument("--initial-equity", type=float, default=1_000.0)
    parser.add_argument("--stop-percent", type=float, default=1.0)
    parser.add_argument("--cost-bps", type=float, default=5.0)
    parser.add_argument("--holdout-percent", type=float, default=30.0)
    parser.add_argument("--min-oos-trades", type=int, default=10)
    parser.add_argument("--ut-key", type=float, default=3.0)
    parser.add_argument("--ut-atr", type=int, default=10)
    parser.add_argument("--include-paper-only", action="store_true")
    parser.add_argument("--output-dir", default="outputs/indicator_comparison")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.lookback_bars < 250:
        raise ValueError("lookback-bars must be at least 250")
    if args.min_oos_trades < 1:
        raise ValueError("min-oos-trades must be positive")
    report = run(args)
    print(json.dumps(report["overall"], indent=2, sort_keys=True))
    print(f"Report: {Path(args.output_dir) / 'utbot_vwap_report.md'}")


if __name__ == "__main__":
    main()
