"""Deterministic strategy experiment tracking and comparison."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from dataclasses import asdict, dataclass, field, is_dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile

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
    source_revision: str = "unversioned"
    random_seed: int = 0
    dataset_source: str = "unknown"
    instrument_config: dict = field(default_factory=dict)
    execution_config: dict = field(default_factory=dict)
    identity_sha256: str = ""

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, values):
        payload = dict(values)
        payload.setdefault("source_revision", "unversioned")
        payload.setdefault("random_seed", 0)
        payload.setdefault("dataset_source", "unknown")
        payload.setdefault("instrument_config", {})
        payload.setdefault("execution_config", {})
        payload.setdefault("identity_sha256", "")
        return cls(**payload)


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


def _json_value(value):
    """Convert experiment configuration into stable JSON-compatible data."""

    if is_dataclass(value) and not isinstance(value, type):
        return _json_value(asdict(value))

    if isinstance(value, dict):
        return {
            str(key): _json_value(item)
            for key, item in value.items()
        }

    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]

    if isinstance(value, Path):
        return str(value)

    return value


def _source_revision():
    """
    Resolve the source revision without making experiment creation depend on Git.

    CI and release jobs can pin ``FOREX_BOT_SOURCE_REVISION``. Local runs use
    the checked-out commit when available and otherwise remain explicit about
    being unversioned.
    """

    configured = os.environ.get("FOREX_BOT_SOURCE_REVISION")

    if configured:
        return configured.strip()

    try:
        completed = subprocess.run(
            ["git", "rev-parse", "--verify", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=2
        )
    except (
        FileNotFoundError,
        subprocess.SubprocessError
    ):
        return "unversioned"

    revision = completed.stdout.strip()
    return revision or "unversioned"


def _atomic_write(path, content):
    """Atomically replace one deterministic research artifact."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None

    try:
        with NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            delete=False
        ) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
            temporary = Path(handle.name)

        temporary.replace(path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


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
        report,
        *,
        source_revision=None,
        random_seed=0,
        instrument_config=None,
        execution_config=None
    ):
        if not isinstance(dataset, DatasetMetadata):
            raise ExperimentError(
                "dataset must be DatasetMetadata"
            )

        if not isinstance(report, PerformanceReport):
            raise ExperimentError(
                "report must be PerformanceReport"
            )

        if isinstance(random_seed, bool) or not isinstance(
            random_seed,
            int
        ):
            raise ExperimentError("random_seed must be an integer")

        canonical_parameters = json.loads(
            _canonical_json(_json_value(parameters))
        )
        canonical_instrument = json.loads(
            _canonical_json(
                _json_value(instrument_config or {})
            )
        )
        canonical_execution = json.loads(
            _canonical_json(
                _json_value(execution_config or {})
            )
        )
        revision = str(
            source_revision
            if source_revision is not None
            else _source_revision()
        ).strip()

        if not revision:
            raise ExperimentError(
                "source_revision cannot be empty"
            )

        identity = {
            "strategy": str(strategy),
            "dataset_version": dataset.dataset_version,
            "dataset_sha256": dataset.content_sha256,
            "symbol": dataset.symbol,
            "timeframe": dataset.timeframe,
            "parameters": canonical_parameters,
            "source_revision": revision,
            "random_seed": random_seed,
            "instrument_config": canonical_instrument,
            "execution_config": canonical_execution
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
            ending_equity=report.ending_equity(),
            source_revision=revision,
            random_seed=random_seed,
            dataset_source=dataset.source,
            instrument_config=canonical_instrument,
            execution_config=canonical_execution,
            identity_sha256=digest
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
            _atomic_write(path, content.encode("utf-8"))

        return path

    def record(
        self,
        strategy,
        dataset,
        parameters,
        trades,
        initial_equity,
        equity_curve=None,
        *,
        source_revision=None,
        random_seed=0,
        instrument_config=None,
        execution_config=None
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
            report,
            source_revision=source_revision,
            random_seed=random_seed,
            instrument_config=instrument_config,
            execution_config=execution_config
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
        *,
        source_revision=None,
        random_seed=0,
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
            equity_curve=engine.equity_history,
            source_revision=source_revision,
            random_seed=random_seed,
            instrument_config=engine.instrument,
            execution_config={
                "initial_equity": engine.initial_equity,
                "risk_percent": engine.risk_percent,
                "same_bar_policy": engine.same_bar_policy,
                "force_close": engine.force_close
            }
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
                "ending_equity",
                "source_revision",
                "random_seed",
                "dataset_source",
                "instrument_config",
                "execution_config",
                "identity_sha256"
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

        for column in (
            "parameters",
            "instrument_config",
            "execution_config"
        ):
            if column in table.columns:
                table[column] = table[column].map(
                    _canonical_json
                )

        content = table.to_csv(
            None,
            index=False,
            lineterminator="\n"
        ).encode("utf-8")
        _atomic_write(path, content)
        return path
