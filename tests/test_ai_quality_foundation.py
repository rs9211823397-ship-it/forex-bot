import csv
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
import json

import pytest

from ai.dataset import (
    AppendOnlyTradeDataset,
    DatasetValidationError,
    TradeOutcome,
)
from ai.features import (
    FEATURE_SCHEMA_V1,
    FeatureSnapshot,
    FeatureValidationError,
    PointInTimeFeatureExtractor,
)
from ai.model import (
    FilterAction,
    QualityEstimate,
    TradeQualityFilter,
)


DECISION_TIME = datetime(2026, 1, 5, 10, 0, tzinfo=timezone.utc)


def make_snapshot(**overrides):
    values = {
        "market_regime": "TRENDING",
        "htf_regime": "BULLISH",
        "atr": 0.0012,
        "adx": 31.0,
        "rsi": 58.0,
        "quality_score": 82.0,
    }
    values.update(overrides.pop("feature_values", {}))
    return PointInTimeFeatureExtractor().extract(
        decision_time=overrides.pop("decision_time", DECISION_TIME),
        symbol=overrides.pop("symbol", "eurusd"),
        timeframe=overrides.pop("timeframe", "15m"),
        existing_direction=overrides.pop(
            "existing_direction",
            "BUY",
        ),
        feature_values=values,
        candle_close_times=overrides.pop(
            "candle_close_times",
            [DECISION_TIME - timedelta(minutes=15), DECISION_TIME],
        ),
        confirmation_times=overrides.pop(
            "confirmation_times",
            {
                "htf_regime": DECISION_TIME - timedelta(hours=1),
                "structure": DECISION_TIME - timedelta(minutes=15),
            },
        ),
        **overrides,
    )


def test_snapshot_is_immutable_and_normalized():
    snapshot = make_snapshot()

    assert snapshot.symbol == "EURUSD"
    assert snapshot.existing_direction == "BUY"
    assert snapshot.decision_time.tzinfo == timezone.utc

    with pytest.raises(FrozenInstanceError):
        snapshot.symbol = "GBPUSD"

    with pytest.raises(TypeError):
        snapshot.features["atr"] = 999


def test_feature_order_and_missing_value_policy_are_stable():
    snapshot = make_snapshot()

    assert tuple(snapshot.features) == FEATURE_SCHEMA_V1.fields
    assert snapshot.value("ema20") is None
    assert snapshot.value("atr") == 0.0012
    assert list(snapshot.to_record()["features"]) == list(
        FEATURE_SCHEMA_V1.fields
    )


@pytest.mark.parametrize(
    "field_name",
    [
        "outcome",
        "future_close",
        "next_return",
        "exit_price",
        "realized_pnl",
        "label_win",
    ],
)
def test_outcome_and_future_fields_are_rejected(field_name):
    with pytest.raises(FeatureValidationError, match="cannot be used"):
        make_snapshot(feature_values={field_name: 1})


def test_unknown_schema_and_feature_are_rejected():
    valid = make_snapshot()
    with pytest.raises(FeatureValidationError, match="Unsupported"):
        FeatureSnapshot(
            schema_version="99.0.0",
            decision_time=valid.decision_time,
            symbol=valid.symbol,
            timeframe=valid.timeframe,
            existing_direction=valid.existing_direction,
            ordered_values=valid.ordered_values,
            available_at=valid.available_at,
        )

    with pytest.raises(FeatureValidationError, match="Unknown feature"):
        make_snapshot(feature_values={"invented_signal": 1})


@pytest.mark.parametrize(
    ("time_argument", "kwargs"),
    [
        (
            "candle",
            {"candle_close_times": [DECISION_TIME + timedelta(seconds=1)]},
        ),
        (
            "confirmed",
            {
                "confirmation_times": {
                    "structure": DECISION_TIME + timedelta(seconds=1)
                }
            },
        ),
        (
            "source",
            {
                "availability_times": {
                    "indicator": DECISION_TIME + timedelta(seconds=1)
                }
            },
        ),
    ],
)
def test_future_inputs_fail_closed(time_argument, kwargs):
    with pytest.raises(
        FeatureValidationError,
        match="not available",
    ):
        make_snapshot(**kwargs)


def test_snapshot_serialization_is_deterministic():
    first = make_snapshot()
    second = make_snapshot()

    assert first == second
    assert first.to_json() == second.to_json()
    decoded = json.loads(first.to_json())
    assert decoded["decision_time"].endswith("Z")
    assert list(decoded["features"]) == list(FEATURE_SCHEMA_V1.fields)


def test_snapshot_requires_an_explicit_availability_audit_trail():
    with pytest.raises(FeatureValidationError, match="availability source"):
        make_snapshot(
            candle_close_times=[],
            confirmation_times={},
        )


def test_dataset_keeps_decisions_and_outcomes_separate():
    dataset = AppendOnlyTradeDataset()
    snapshot = make_snapshot()
    outcome = TradeOutcome(
        exit_time=DECISION_TIME + timedelta(hours=2),
        exit_reason="TARGET",
        profit_loss=200.0,
        r_multiple=2.0,
    )

    decision_event = dataset.append_snapshot("trade-001", snapshot)
    outcome_event = dataset.append_outcome("trade-001", outcome)

    assert decision_event.outcome is None
    assert outcome_event.snapshot is None
    assert "profit_loss" not in snapshot.features

    joined = dataset.completed_records()
    assert len(joined) == 1
    assert set(joined[0]) == {"trade_id", "snapshot", "outcome"}
    assert "outcome" not in joined[0]["snapshot"]["features"]


def test_dataset_is_append_only_and_validates_lifecycle(tmp_path):
    dataset = AppendOnlyTradeDataset()
    snapshot = make_snapshot()
    dataset.append_snapshot("trade-001", snapshot)

    with pytest.raises(DatasetValidationError, match="already exists"):
        dataset.append_snapshot("trade-001", snapshot)

    with pytest.raises(
        DatasetValidationError,
        match="previously appended",
    ):
        dataset.append_outcome(
            "unknown",
            TradeOutcome(
                exit_time=DECISION_TIME,
                exit_reason="STOP",
                profit_loss=-100,
                r_multiple=-1,
            ),
        )

    with pytest.raises(
        DatasetValidationError,
        match="cannot precede",
    ):
        dataset.append_outcome(
            "trade-001",
            TradeOutcome(
                exit_time=DECISION_TIME - timedelta(seconds=1),
                exit_reason="STOP",
                profit_loss=-100,
                r_multiple=-1,
            ),
        )

    destination = tmp_path / "events.jsonl"
    dataset.export_jsonl(destination)
    with pytest.raises(FileExistsError, match="Refusing to overwrite"):
        dataset.export_jsonl(destination)


def test_jsonl_and_csv_exports_are_reproducible(tmp_path):
    def populated_dataset():
        dataset = AppendOnlyTradeDataset()
        dataset.append_snapshot("trade-001", make_snapshot())
        dataset.append_outcome(
            "trade-001",
            TradeOutcome(
                exit_time=DECISION_TIME + timedelta(hours=1),
                exit_reason="STOP",
                profit_loss=-100,
                r_multiple=-1,
            ),
        )
        return dataset

    first_json = populated_dataset().export_jsonl(
        tmp_path / "first.jsonl"
    )
    second_json = populated_dataset().export_jsonl(
        tmp_path / "second.jsonl"
    )
    assert first_json.read_bytes() == second_json.read_bytes()

    first_csv = populated_dataset().export_csv(tmp_path / "first.csv")
    second_csv = populated_dataset().export_csv(tmp_path / "second.csv")
    assert first_csv.read_bytes() == second_csv.read_bytes()

    with first_csv.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert [row["record_type"] for row in rows] == [
        "decision",
        "outcome",
    ]
    assert rows[0]["profit_loss"] == ""
    assert rows[1]["feature.atr"] == ""


class CountingModel:
    def __init__(self, score):
        self.score = score
        self.calls = 0

    def estimate(self, snapshot):
        self.calls += 1
        assert isinstance(snapshot, FeatureSnapshot)
        return QualityEstimate(
            score=self.score,
            model_version="test-model-1",
        )


def test_quality_filter_is_disabled_by_default_and_does_not_call_model():
    model = CountingModel(0.0)
    result = TradeQualityFilter(model=model).evaluate(make_snapshot())

    assert result.action is FilterAction.ALLOW
    assert result.enabled is False
    assert result.quality_score is None
    assert model.calls == 0
    assert not hasattr(result, "direction")


@pytest.mark.parametrize(
    ("score", "expected_action"),
    [(0.8, FilterAction.ALLOW), (0.79, FilterAction.BLOCK)],
)
def test_enabled_filter_only_allows_or_blocks_existing_setup(
    score,
    expected_action,
):
    result = TradeQualityFilter(
        enabled=True,
        model=CountingModel(score),
        minimum_quality=0.8,
    ).evaluate(make_snapshot(existing_direction="SELL"))

    assert result.action is expected_action
    assert result.enabled is True
    assert result.quality_score == score
    assert not hasattr(result, "direction")


def test_enabled_filter_requires_explicit_validated_dependencies():
    with pytest.raises(ValueError, match="requires a TradeQualityModel"):
        TradeQualityFilter(enabled=True, minimum_quality=0.8)

    with pytest.raises(ValueError, match="explicit minimum_quality"):
        TradeQualityFilter(enabled=True, model=CountingModel(0.8))

    with pytest.raises(ValueError, match="between 0 and 1"):
        TradeQualityFilter(
            enabled=True,
            model=CountingModel(0.8),
            minimum_quality=1.1,
        )
