from datetime import datetime, timezone

import pytest

from mt5_time import (
    mt5_epoch_to_utc_datetime,
    mt5_epoch_to_utc_seconds,
    utc_datetime_to_mt5_server_time,
    validate_mt5_server_utc_offset_minutes,
)


def test_winprofx_server_epoch_is_normalized_from_utc_plus_three():
    actual = datetime(2026, 8, 24, 14, 1, 37, tzinfo=timezone.utc)
    broker_epoch = datetime(2026, 8, 24, 17, 1, 37, tzinfo=timezone.utc).timestamp()

    assert mt5_epoch_to_utc_datetime(broker_epoch, 180) == actual
    assert mt5_epoch_to_utc_seconds(broker_epoch, 180) == actual.timestamp()


def test_history_query_boundary_is_shifted_to_broker_server_clock():
    actual = datetime(2026, 8, 24, 14, 0, tzinfo=timezone.utc)
    assert utc_datetime_to_mt5_server_time(actual, 180) == datetime(
        2026, 8, 24, 17, 0, tzinfo=timezone.utc
    )


@pytest.mark.parametrize("value", [-841, 841, True, 1.5])
def test_invalid_server_offsets_fail_closed(value):
    with pytest.raises(ValueError):
        validate_mt5_server_utc_offset_minutes(value)
