"""Deterministic tests for the non-live production foundation."""

from datetime import datetime, timezone
import inspect
import json

import pytest

from accounts.manager import AccountConfig, AccountManager
from accounts.safety import (
    EmergencyStopStore,
    ExposureAction,
    MaxExposureGuard,
)
from bot_controller import BotController
from broker.adapters import ExchangeAdapter, MT5Adapter
from broker.contracts import (
    BrokerAdapter,
    BrokerOrderSnapshot,
    ExecutionUnavailableError,
)
from broker.reconciliation import reconcile_orders
from config.production import ProductionConfig
from execution.models import OrderRequest
from logs.structured import StructuredEventLogger


NOW = datetime(2025, 5, 1, 12, tzinfo=timezone.utc)


def _broker_order(**overrides):
    values = {
        "order_id": "broker-order-1",
        "client_order_id": "client-order-1",
        "account_id": "alpha",
        "symbol": "EURUSD",
        "side": "BUY",
        "quantity": 1.0,
        "filled_quantity": 0.0,
        "state": "ACKNOWLEDGED",
        "updated_time": NOW,
    }
    values.update(overrides)
    return BrokerOrderSnapshot(**values)


def _order_request():
    return OrderRequest(
        client_order_id="client-order-1",
        symbol="EURUSD",
        side="BUY",
        quantity=1.0,
        created_time=NOW,
    )


@pytest.mark.parametrize("adapter_type", [MT5Adapter, ExchangeAdapter])
def test_live_adapter_stubs_fail_closed_without_network(adapter_type):
    adapter = adapter_type()

    assert isinstance(adapter, BrokerAdapter)
    assert adapter.is_live is False
    assert adapter.health().ready is False
    with pytest.raises(ExecutionUnavailableError):
        adapter.submit_order("alpha", _order_request())
    with pytest.raises(ExecutionUnavailableError):
        adapter.account_snapshot("alpha")


def test_reconciliation_is_deterministic_and_reports_exact_mismatch():
    internal = [_broker_order()]
    broker = [_broker_order(filled_quantity=0.5)]

    first = reconcile_orders(internal, broker, as_of=NOW)
    second = reconcile_orders(
        tuple(reversed(internal)),
        tuple(reversed(broker)),
        as_of=NOW,
    )

    assert first == second
    assert first.is_reconciled is False
    assert first.matched_orders == 0
    assert len(first.issues) == 1
    assert first.issues[0].field == "filled_quantity"


def test_reconciliation_rejects_duplicate_order_ids():
    duplicate = _broker_order()

    with pytest.raises(ValueError, match="Duplicate internal"):
        reconcile_orders(
            [duplicate, duplicate],
            [],
            as_of=NOW,
        )


def test_account_manager_isolates_storage_config_and_lifecycle(tmp_path):
    manager = AccountManager(tmp_path, max_accounts=2)
    alpha = manager.register(AccountConfig("alpha", "paper"))
    beta = manager.register(AccountConfig("beta", "paper", currency="EUR"))

    assert alpha.storage_dir != beta.storage_dir
    assert alpha.storage_dir.parent == beta.storage_dir.parent
    assert manager.account_ids == ("alpha", "beta")
    assert manager.start("alpha") == "BOT STARTED"
    assert manager.snapshot("alpha").status == "RUNNING"
    assert manager.snapshot("beta").status == "STOPPED"

    alpha_config = json.loads(
        (alpha.storage_dir / "config.json").read_text(encoding="utf-8")
    )
    assert alpha_config["account_id"] == "alpha"
    assert not any(
        "password" in key or "token" in key or "secret" in key
        for key in alpha_config
    )

    restored = AccountManager(tmp_path, max_accounts=2)
    assert tuple(item.config.account_id for item in restored.load()) == (
        "alpha",
        "beta",
    )


def test_account_ids_cannot_escape_isolated_storage(tmp_path):
    manager = AccountManager(tmp_path)

    with pytest.raises(ValueError, match="account_id"):
        manager.register(AccountConfig("../escape", "paper"))


def test_emergency_stop_persists_and_blocks_account_start(tmp_path):
    store = EmergencyStopStore(tmp_path / "safety" / "stop.json")
    assert store.status().active is False
    store.activate("operator request", changed_at=NOW)

    reloaded = EmergencyStopStore(tmp_path / "safety" / "stop.json")
    assert reloaded.status().active is True
    assert reloaded.status().reason == "operator request"

    manager = AccountManager(tmp_path / "accounts-state", emergency_stop=reloaded)
    manager.register(AccountConfig("alpha", "paper"))
    assert manager.start("alpha") == "BLOCKED BY EMERGENCY STOP"

    reloaded.clear(changed_at=NOW)
    assert manager.start("alpha") == "BOT STARTED"


def test_corrupt_emergency_stop_state_fails_closed(tmp_path):
    path = tmp_path / "stop.json"
    path.write_text("{not-json", encoding="utf-8")

    state = EmergencyStopStore(path).status()

    assert state.active is True
    assert state.reason == "EMERGENCY_STOP_STATE_INVALID"


def test_max_exposure_guard_allows_boundary_and_blocks_excess():
    guard = MaxExposureGuard(100_000.0)

    at_limit = guard.evaluate(75_000.0, 25_000.0)
    over_limit = guard.evaluate(75_000.0, 25_000.01)

    assert at_limit.action is ExposureAction.ALLOW
    assert at_limit.allowed is True
    assert over_limit.action is ExposureAction.BLOCK
    assert over_limit.reason == "MAX_EXPOSURE_EXCEEDED"


def test_production_config_loads_only_validated_non_secret_values(tmp_path):
    config = ProductionConfig.from_env(
        {
            "FOREX_BOT_ENVIRONMENT": "production",
            "FOREX_BOT_STATE_DIR": str(tmp_path / "state"),
            "FOREX_BOT_LOG_DIR": str(tmp_path / "logs"),
            "FOREX_BOT_LOG_LEVEL": "WARNING",
            "FOREX_BOT_MAX_ACCOUNTS": "4",
            "FOREX_BOT_MAX_GROSS_EXPOSURE": "250000",
            "FOREX_BOT_LIVE_TRADING": "false",
            "FOREX_BOT_API_TOKEN": "must-not-be-read",
        }
    )

    public = config.as_public_dict()
    assert config.environment == "production"
    assert config.max_accounts == 4
    assert config.max_gross_exposure == 250_000.0
    assert all(
        term not in key.lower()
        for key in public
        for term in ("password", "secret", "token", "api_key")
    )


def test_live_configuration_requires_explicit_acknowledgement():
    with pytest.raises(ValueError, match="acknowledgement"):
        ProductionConfig.from_env(
            {"FOREX_BOT_LIVE_TRADING": "true"}
        )


def test_structured_logger_writes_identifiers_and_rotates(tmp_path):
    path = tmp_path / "events.jsonl"
    with StructuredEventLogger(
        path,
        max_bytes=220,
        backup_count=2,
    ) as logger:
        for index in range(5):
            logger.log_event(
                "ORDER_EVENT",
                f"order event {index}",
                correlation_id="correlation-1",
                account_id="alpha",
                order_id=f"order-{index}",
                event_time=NOW,
                payload={"state": "ACKNOWLEDGED", "sequence": index},
            )

    files = sorted(tmp_path.glob("events.jsonl*"))
    assert path in files
    assert len(files) >= 2
    records = [
        json.loads(line)
        for file_path in files
        for line in file_path.read_text(encoding="utf-8").splitlines()
    ]
    assert all(record["correlation_id"] == "correlation-1" for record in records)
    assert all(record["account_id"] == "alpha" for record in records)
    assert all(record["order_id"] for record in records)


def test_structured_logger_rejects_secret_payloads(tmp_path):
    with StructuredEventLogger(tmp_path / "events.jsonl") as logger:
        with pytest.raises(ValueError, match="Sensitive"):
            logger.log_event(
                "CONFIG",
                "unsafe payload",
                correlation_id="correlation-1",
                event_time=NOW,
                payload={"api_token": "secret-value"},
            )


def test_existing_bot_controller_api_and_responses_remain_unchanged():
    assert str(inspect.signature(BotController)) == "()"
    assert str(inspect.signature(BotController.start_bot)) == "(self)"

    controller = BotController()
    assert controller.status() == "STOPPED"
    assert controller.start_bot() == "BOT STARTED"
    assert controller.pause_bot() == "BOT PAUSED"
    assert controller.resume_bot() == "BOT RESUMED"
    assert controller.stop_bot() == "BOT STOPPED"
