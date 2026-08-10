from validation.restart_soak import restart_soak_report


def snapshot(heartbeat, *, peak=100.0, ticket=10):
    return {
        "runtime": {
            "account_id": "exness_demo",
            "mt5_login": 123,
            "mt5_server": "Broker-Demo",
            "risk_baseline_utc": "2026-01-01T00:00:00+00:00",
            "risk_state_identity": "MT5_DEMO|mt5:123:broker-demo|baseline:x",
            "equity_peak": peak,
            "heartbeat_utc": heartbeat,
            "status": "RUNNING",
            "open_positions": 1,
        },
        "positions": [{"ticket": ticket, "symbol": "EURUSDm"}],
    }


def test_restart_soak_preserves_identity_peak_and_positions():
    report = restart_soak_report(
        snapshot("2026-01-01T00:00:00Z"),
        snapshot("2026-01-01T00:05:00Z", peak=101.0),
    )
    assert report["passed"] is True


def test_restart_soak_fails_if_peak_or_position_is_lost():
    report = restart_soak_report(
        snapshot("2026-01-01T00:00:00Z", peak=101.0),
        snapshot("2026-01-01T00:05:00Z", peak=100.0, ticket=11),
    )
    assert report["passed"] is False
    assert report["checks"]["equity_peak_preserved"] is False
    assert report["checks"]["managed_positions_preserved"] is False
