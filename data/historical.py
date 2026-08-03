"""Versioned, reproducible local OHLCV storage and CSV replay."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections import OrderedDict
from dataclasses import asdict, dataclass
from io import BytesIO
from math import isfinite
from pathlib import Path
from tempfile import NamedTemporaryFile

import pandas as pd

from data.timeframes import (
    TimeframeError,
    candle_close_times,
    candle_open_times,
    normalize_timeframe,
    normalize_timestamp
)


class HistoricalDataError(ValueError):
    """Raised when historical data is invalid or cannot be reproduced."""


@dataclass(frozen=True)
class DatasetMetadata:
    schema_version: str
    dataset_version: str
    content_sha256: str
    symbol: str
    timeframe: str
    source: str
    rows: int
    start_time: str | None
    end_time: str | None
    columns: tuple[str, ...]

    def to_dict(self):
        result = asdict(self)
        result["columns"] = list(self.columns)
        return result

    @classmethod
    def from_dict(cls, values):
        payload = dict(values)
        payload["columns"] = tuple(payload["columns"])
        return cls(**payload)


class HistoricalDataStore:
    """Persist immutable, content-addressed OHLCV datasets."""

    SCHEMA_VERSION = "ohlcv-v1"
    REQUIRED_COLUMNS = ("open", "high", "low", "close")
    OPTIONAL_COLUMNS = ("volume",)

    def __init__(self, root="data/cache"):
        self.root = Path(root)

    @staticmethod
    def _safe_component(value):
        normalized = re.sub(
            r"[^A-Za-z0-9_.-]+",
            "_",
            str(value).strip()
        )

        if not normalized:
            raise HistoricalDataError(
                "Dataset path component cannot be empty"
            )

        return normalized

    def _dataset_directory(self, symbol, timeframe):
        return (
            self.root
            / self._safe_component(symbol)
            / self._safe_component(
                normalize_timeframe(timeframe)
            )
        )

    @staticmethod
    def _validate_prices(frame):
        for column in HistoricalDataStore.REQUIRED_COLUMNS:
            numeric = pd.to_numeric(
                frame[column],
                errors="raise"
            )

            if not all(isfinite(float(value)) for value in numeric):
                raise HistoricalDataError(
                    f"{column} must contain finite values"
                )

            frame[column] = numeric.astype(float)

        if "volume" in frame.columns:
            volume = pd.to_numeric(
                frame["volume"],
                errors="raise"
            )

            if not all(isfinite(float(value)) for value in volume):
                raise HistoricalDataError(
                    "volume must contain finite values"
                )

            frame["volume"] = volume.astype(float)

        invalid = (
            (frame["high"] < frame[["open", "close"]].max(axis=1))
            | (frame["low"] > frame[["open", "close"]].min(axis=1))
            | (frame["high"] < frame["low"])
        )

        if invalid.any():
            raise HistoricalDataError(
                "Historical data contains invalid OHLC geometry"
            )

    def prepare(
        self,
        data,
        timeframe,
        as_of=None
    ):
        """Normalize raw candles and optionally remove incomplete candles."""

        if not isinstance(data, pd.DataFrame):
            raise HistoricalDataError(
                "Historical data must be a pandas DataFrame"
            )

        normalized_timeframe = normalize_timeframe(timeframe)
        frame = data.copy()

        if hasattr(frame.columns, "levels"):
            frame.columns = frame.columns.get_level_values(0)

        frame.columns = [
            str(column).lower()
            for column in frame.columns
        ]

        if frame.columns.duplicated().any():
            raise HistoricalDataError(
                "Historical data contains duplicate columns"
            )

        missing = [
            column for column in self.REQUIRED_COLUMNS
            if column not in frame.columns
        ]

        if missing:
            raise HistoricalDataError(
                "Historical data missing columns: "
                + ", ".join(missing)
            )

        try:
            opens = candle_open_times(
                frame,
                normalized_timeframe
            )
            closes = candle_close_times(
                frame,
                normalized_timeframe
            )
        except TimeframeError as exc:
            raise HistoricalDataError(str(exc)) from exc

        frame.index = opens
        frame.index.name = "open_time"
        frame["close_time"] = closes
        selected_columns = [
            *self.REQUIRED_COLUMNS,
            *[
                column for column in self.OPTIONAL_COLUMNS
                if column in frame.columns
            ],
            "close_time"
        ]
        frame = frame[selected_columns]
        self._validate_prices(frame)

        if as_of is not None:
            cutoff = normalize_timestamp(as_of, "as_of")
            frame = frame.loc[
                frame["close_time"] <= cutoff
            ].copy()

        frame.attrs["timeframe"] = normalized_timeframe
        return frame

    @staticmethod
    def _csv_bytes(frame):
        storage = frame.reset_index()
        text = storage.to_csv(
            index=False,
            float_format="%.17g",
            date_format="%Y-%m-%dT%H:%M:%S.%fZ",
            lineterminator="\n"
        )
        return text.encode("utf-8")

    @staticmethod
    def _sha256(content):
        return hashlib.sha256(content).hexdigest()

    def describe(
        self,
        data,
        symbol,
        timeframe,
        source="unknown",
        as_of=None
    ):
        frame = self.prepare(
            data,
            timeframe,
            as_of=as_of
        )
        content = self._csv_bytes(frame)
        digest = self._sha256(content)
        version = f"{self.SCHEMA_VERSION}-{digest[:16]}"

        metadata = DatasetMetadata(
            schema_version=self.SCHEMA_VERSION,
            dataset_version=version,
            content_sha256=digest,
            symbol=str(symbol),
            timeframe=normalize_timeframe(timeframe),
            source=str(source),
            rows=len(frame),
            start_time=(
                frame["close_time"].iloc[0].isoformat()
                if not frame.empty
                else None
            ),
            end_time=(
                frame["close_time"].iloc[-1].isoformat()
                if not frame.empty
                else None
            ),
            columns=tuple(frame.columns)
        )
        return frame, metadata, content

    @staticmethod
    def _atomic_write(path, content):
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

    def prefix_cache(
        self,
        data,
        timeframe,
        max_entries=32,
        max_cached_rows=250000
    ):
        """
        Build a bounded point-in-time cache from an immutable data snapshot.

        Cached selections are keyed by the number of candles closed at the
        requested decision time. Future rows are never part of a returned
        prefix.
        """

        return CausalAsOfCache(
            data,
            timeframe,
            max_entries=max_entries,
            max_cached_rows=max_cached_rows
        )

    def save(
        self,
        data,
        symbol,
        timeframe,
        source="unknown",
        as_of=None
    ):
        """Save one immutable dataset and return its metadata."""

        _, metadata, content = self.describe(
            data,
            symbol,
            timeframe,
            source=source,
            as_of=as_of
        )
        directory = self._dataset_directory(
            symbol,
            timeframe
        )
        csv_path = directory / f"{metadata.dataset_version}.csv"
        manifest_path = (
            directory / f"{metadata.dataset_version}.json"
        )
        latest_path = directory / "latest.json"
        manifest = json.dumps(
            metadata.to_dict(),
            indent=2,
            sort_keys=True
        ).encode("utf-8") + b"\n"

        if csv_path.exists():
            existing = csv_path.read_bytes()

            if self._sha256(existing) != metadata.content_sha256:
                raise HistoricalDataError(
                    "Existing dataset content does not match its version"
                )
        else:
            self._atomic_write(csv_path, content)

        if not manifest_path.exists():
            self._atomic_write(manifest_path, manifest)

        latest = json.dumps(
            {"dataset_version": metadata.dataset_version},
            indent=2,
            sort_keys=True
        ).encode("utf-8") + b"\n"
        self._atomic_write(latest_path, latest)
        return metadata

    def list_versions(self, symbol, timeframe):
        directory = self._dataset_directory(
            symbol,
            timeframe
        )

        if not directory.exists():
            return []

        return sorted(
            path.stem
            for path in directory.glob(
                f"{self.SCHEMA_VERSION}-*.json"
            )
        )

    def _resolve_version(self, symbol, timeframe, version):
        if version is not None:
            return str(version)

        latest_path = (
            self._dataset_directory(symbol, timeframe)
            / "latest.json"
        )

        if not latest_path.exists():
            raise HistoricalDataError(
                "No cached dataset is available"
            )

        try:
            return json.loads(
                latest_path.read_text(encoding="utf-8")
            )["dataset_version"]
        except (KeyError, json.JSONDecodeError) as exc:
            raise HistoricalDataError(
                "Latest dataset pointer is invalid"
            ) from exc

    def metadata(self, symbol, timeframe, version=None):
        resolved = self._resolve_version(
            symbol,
            timeframe,
            version
        )
        path = (
            self._dataset_directory(symbol, timeframe)
            / f"{resolved}.json"
        )

        if not path.exists():
            raise HistoricalDataError(
                f"Dataset manifest not found: {resolved}"
            )

        try:
            return DatasetMetadata.from_dict(
                json.loads(path.read_text(encoding="utf-8"))
            )
        except (
            TypeError,
            KeyError,
            json.JSONDecodeError
        ) as exc:
            raise HistoricalDataError(
                "Dataset manifest is invalid"
            ) from exc

    def load(self, symbol, timeframe, version=None):
        """Load and integrity-check one cached dataset."""

        metadata = self.metadata(
            symbol,
            timeframe,
            version
        )
        path = (
            self._dataset_directory(symbol, timeframe)
            / f"{metadata.dataset_version}.csv"
        )

        if not path.exists():
            raise HistoricalDataError(
                "Dataset CSV is missing"
            )

        content = path.read_bytes()

        if self._sha256(content) != metadata.content_sha256:
            raise HistoricalDataError(
                "Dataset integrity check failed"
            )

        return self._read_content(
            content,
            metadata.timeframe,
            expected_version=metadata.dataset_version
        )

    def _read_content(
        self,
        content,
        timeframe,
        expected_version=None
    ):
        content_version = (
            f"{self.SCHEMA_VERSION}-"
            f"{self._sha256(content)[:16]}"
        )

        if (
            expected_version is not None
            and content_version != expected_version
        ):
            raise HistoricalDataError(
                "CSV content does not match expected dataset version"
            )

        try:
            frame = pd.read_csv(BytesIO(content))
        except (OSError, ValueError) as exc:
            raise HistoricalDataError(
                "Could not parse historical CSV"
            ) from exc

        if "open_time" not in frame.columns:
            raise HistoricalDataError(
                "Historical CSV requires open_time"
            )

        frame["open_time"] = pd.to_datetime(
            frame["open_time"],
            utc=True,
            errors="raise"
        )
        frame["close_time"] = pd.to_datetime(
            frame["close_time"],
            utc=True,
            errors="raise"
        )
        frame = frame.set_index("open_time")
        return self.prepare(frame, timeframe)

    def load_csv(
        self,
        path,
        timeframe,
        expected_version=None
    ):
        """Replay an arbitrary local CSV using the same validation."""

        csv_path = Path(path)

        if not csv_path.exists():
            raise HistoricalDataError(
                f"Historical CSV not found: {csv_path}"
            )

        return self._read_content(
            csv_path.read_bytes(),
            normalize_timeframe(timeframe),
            expected_version=expected_version
        )


class CausalAsOfCache:
    """
    Bounded LRU cache for repeated closed-candle prefix selection.

    The constructor takes a deep, validated snapshot. This makes selections
    reproducible even if the caller later mutates its source DataFrame. Every
    returned frame is also copied so downstream research cannot corrupt the
    cached snapshot.
    """

    def __init__(
        self,
        data,
        timeframe,
        *,
        max_entries=32,
        max_cached_rows=250000
    ):
        if isinstance(max_entries, bool) or not isinstance(
            max_entries,
            int
        ):
            raise HistoricalDataError(
                "max_entries must be an integer"
            )

        if max_entries <= 0:
            raise HistoricalDataError(
                "max_entries must be greater than zero"
            )

        if isinstance(max_cached_rows, bool) or not isinstance(
            max_cached_rows,
            int
        ):
            raise HistoricalDataError(
                "max_cached_rows must be an integer"
            )

        if max_cached_rows <= 0:
            raise HistoricalDataError(
                "max_cached_rows must be greater than zero"
            )

        self.timeframe = normalize_timeframe(timeframe)
        self.max_entries = max_entries
        self.max_cached_rows = max_cached_rows
        self._frame = HistoricalDataStore().prepare(
            data,
            self.timeframe
        ).copy(deep=True)
        self._close_times = pd.DatetimeIndex(
            self._frame["close_time"]
        )
        self._cache = OrderedDict()
        self._cached_rows = 0
        self._hits = 0
        self._misses = 0

    def select(self, decision_time):
        """Return candles whose close time is at or before decision_time."""

        cutoff = normalize_timestamp(
            decision_time,
            "decision_time"
        )
        end = int(
            self._close_times.searchsorted(
                cutoff,
                side="right"
            )
        )

        if end in self._cache:
            self._hits += 1
            selected = self._cache.pop(end)
            self._cache[end] = selected
        else:
            self._misses += 1
            selected = self._frame.iloc[:end].copy(deep=True)
            selected.attrs["timeframe"] = self.timeframe

            if len(selected) <= self.max_cached_rows:
                self._cache[end] = selected
                self._cached_rows += len(selected)

                while (
                    len(self._cache) > self.max_entries
                    or self._cached_rows > self.max_cached_rows
                ):
                    _, evicted = self._cache.popitem(
                        last=False
                    )
                    self._cached_rows -= len(evicted)

        return selected.copy(deep=True)

    as_of = select

    def clear(self):
        """Release cached prefixes while retaining the immutable source."""

        self._cache.clear()
        self._cached_rows = 0
        self._hits = 0
        self._misses = 0

    def cache_info(self):
        """Return stable diagnostics without exposing cached market data."""

        return {
            "entries": len(self._cache),
            "max_entries": self.max_entries,
            "cached_rows": self._cached_rows,
            "max_cached_rows": self.max_cached_rows,
            "source_rows": len(self._frame),
            "hits": self._hits,
            "misses": self._misses
        }
