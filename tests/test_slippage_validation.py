import json

from validation.slippage import slippage_report


def write_fills(path, adverse, *, symbol="EURUSD=X", assumed=0.00002):
    with path.open("w", encoding="utf-8") as handle:
        for index, value in enumerate(adverse):
            handle.write(json.dumps({
                "timestamp": f"2026-01-{index + 1:02d}T00:00:00Z",
                "source_symbol": symbol,
                "request_price": 1.1,
                "fill_price": 1.1 + value,
                "fill_price_source": "broker_result",
                "adverse_slippage_price": value,
                "assumed_slippage_price": assumed,
            }) + "\n")


def test_slippage_report_passes_only_with_real_broker_fill_sample(tmp_path):
    path = tmp_path / "fills.jsonl"
    write_fills(path, [0.00001, 0.000015, 0.00002])
    report = slippage_report(path, min_fills=3, min_symbol_fills=3)
    assert report["sample_complete"] is True
    assert report["within_assumption"] is True


def test_slippage_report_rejects_p95_above_backtest_assumption(tmp_path):
    path = tmp_path / "fills.jsonl"
    write_fills(path, [0.00001, 0.00002, 0.00010])
    report = slippage_report(path, min_fills=3, min_symbol_fills=3)
    assert report["sample_complete"] is True
    assert report["within_assumption"] is False
