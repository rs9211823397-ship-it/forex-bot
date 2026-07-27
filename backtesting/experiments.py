"""Deterministic strategy experiment tracking and comparison."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd

from backtesting.backtest_engine import BacktestEngine
from backtesting.performance import PerformanceReport
from data.historical import DatasetMetadata


class ExperimentError(ValueError):
    """Raised when an experiment cannot be recorded reproducibly."""


@dataclass(frozen=True)
class ExperimentRecord:
    experiment_id: str
    strategy: str
    dataset_version: str
    dataset_sha256: str
    symbol: str
    timeframe: str
    parameters: dict
    trades: int
    completed_trades: int
    win_rate: float
    profit_factor: float | str
    max_drawdown: float
    max_drawdown_percent: float
    expectancy: float
    average_r: float
    ending_equity: float

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, values):
        return cls(**values)


def _canonical_json(values):
    try:
        return json.dumps(
            values,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False
        )
    except (TypeError, ValueError) as exc:
        raise ExperimentError(
            "Experiment values must be finite JSON data"
        ) from exc


class ExperimentTracker:
    """Write one immutable JSON report per experiment."""

    def __init__(self, output_dir="outputs/experiments"):
        self.output_dir = Path(output_dir)

    @staticmethod
    def _metric_value(value):
        if value == float("inf"):
            return "Infinity"

        return float(value)

    def build_record(
        self,
        strategy,
        dataset,
        parameters,
        report
    ):
        if not isinstance(dataset, DatasetMetadata):
            raise ExperimentError(
                "dataset must be DatasetMetadata"
            )

        if not isinstance(report, PerformanceReport):
            raise ExperimentError(
                "report must be PerformanceReport"
            )

        canonical_parameters = json.loads(
            _canonical_json(parameters)
        )
        identity = {
            "strategy": str(strategy),
            "dataset_version": dataset.dataset_version,
            "symbol": dataset.symbol,
            "timeframe": dataset.timeframe,
            "parameters": canonical_parameters
        }
        digest = hashlib.sha256(
            _canonical_json(identity).encode("utf-8")
        ).hexdigest()

        return ExperimentRecord(
            experiment_id=f"experiment-{digest[:16]}",
            strategy=str(strategy),
            dataset_version=dataset.dataset_version,
            dataset_sha256=dataset.content_sha256,
            symbol=dataset.symbol,
            timeframe=dataset.timeframe,
            parameters=canonical_parameters,
            trades=report.total_trades(),
            completed_trades=report.total_trades(),
            win_rate=report.win_rate(),
            profit_factor=self._metric_value(
                report.profit_factor()
            ),
            max_drawdown=report.max_drawdown(),
            max_drawdown_percent=(
                report.max_drawdown_percent()
            ),
            expectancy=report.expectancy(),
            average_r=report.average_r(),
            ending_equity=report.ending_equity()
        )

    def save(self, record):
        if not isinstance(record, ExperimentRecord):
            raise ExperimentError(
                "record must be ExperimentRecord"
            )

        self.output_dir.mkdir(parents=True, exist_ok=True)
        path = self.output_dir / f"{record.experiment_id}.json"
        content = json.dumps(
            record.to_dict(),
            indent=2,
            sort_keys=True,
            allow_nan=False
        ) + "\n"

        if path.exists():
            existing = path.read_text(encoding="utf-8")

            if existing != content:
                raise ExperimentError(
                    "Experiment ID collision with different results"
                )
        else:
            path.write_text(content, encoding="utf-8")

        return path

    def record(
        self,
        strategy,
        dataset,
        parameters,
        trades,
        initial_equity,
        equity_curve=None
    ):
        report = PerformanceReport(
            trades,
            initial_equity=initial_equity,
            equity_curve=equity_curve
        )
        record = self.build_record(
            strategy,
            dataset,
            parameters,
            report
        )
        self.save(record)
        return record

    def run_backtest(
        self,
        strategy_name,
        dataset,
        parameters,
        data,
        strategy,
        **engine_options
    ):
        """Run the existing engine and persist its experiment metrics."""

        engine = BacktestEngine(
            data,
            strategy,
            **engine_options
        )
        trades = engine.run()
        record = self.record(
            strategy_name,
            dataset,
            parameters,
            trades,
            engine.initial_equity,
            equity_curve=engine.equity_history
        )
        return record, engine

    def load(self, experiment_id):
        path = self.output_dir / f"{experiment_id}.json"

        if not path.exists():
            raise ExperimentError(
                f"Experiment report not found: {experiment_id}"
            )

        try:
            return ExperimentRecord.from_dict(
                json.loads(path.read_text(encoding="utf-8"))
            )
        except (
            TypeError,
            KeyError,
            json.JSONDecodeError
        ) as exc:
            raise ExperimentError(
                "Experiment report is invalid"
            ) from exc

    @staticmethod
    def compare(records):
        """Return a stable comparison table without ranking or tuning."""

        rows = [
            record.to_dict()
            if isinstance(record, ExperimentRecord)
            else dict(record)
            for record in records
        ]

        if not rows:
            return pd.DataFrame(columns=[
                "experiment_id",
                "strategy",
                "dataset_version",
                "dataset_sha256",
                "symbol",
                "timeframe",
                "parameters",
                "trades",
                "completed_trades",
                "win_rate",
                "profit_factor",
                "max_drawdown",
                "max_drawdown_percent",
                "expectancy",
                "average_r",
                "ending_equity"
            ])

        return (
            pd.DataFrame(rows)
            .sort_values("experiment_id")
            .reset_index(drop=True)
        )

    def save_comparison(
        self,
        records,
        filename="comparison.csv"
    ):
        self.output_dir.mkdir(parents=True, exist_ok=True)
        path = self.output_dir / filename
        table = self.compare(records).copy()

        if "parameters" in table.columns:
            table["parameters"] = table["parameters"].map(
                _canonical_json
            )

        table.to_csv(
            path,
            index=False,
            lineterminator="\n"
        )
        return path
