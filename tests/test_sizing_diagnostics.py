import pandas as pd
import pytest

from scripts.sizing_diagnostics import atr14, classify_min_lot_risk


def test_atr14_uses_completed_history_without_future_dependency():
    index = pd.date_range("2026-01-01", periods=20, freq="15min", tz="UTC")
    frame = pd.DataFrame(
        {
            "high": [101.0 + i for i in range(20)],
            "low": [99.0 + i for i in range(20)],
            "close": [100.0 + i for i in range(20)],
        },
        index=index,
    )
    value = atr14(frame)
    assert value == pytest.approx(2.0)


def test_atr14_rejects_insufficient_history():
    frame = pd.DataFrame({"high": [2.0], "low": [1.0], "close": [1.5]})
    with pytest.raises(ValueError, match="15 completed candles"):
        atr14(frame)


def test_min_lot_risk_classification():
    status, ratio = classify_min_lot_risk(0.80, 1.00)
    assert status == "EXECUTABLE"
    assert ratio == pytest.approx(0.8)

    status, ratio = classify_min_lot_risk(1.20, 1.00)
    assert status == "TOO_SMALL_FOR_MIN_LOT"
    assert ratio == pytest.approx(1.2)


def test_min_lot_risk_requires_positive_budget():
    with pytest.raises(ValueError, match="risk_budget"):
        classify_min_lot_risk(1.0, 0.0)
