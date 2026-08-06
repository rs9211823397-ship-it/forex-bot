import os
from pathlib import Path

import pytest

from scripts.codespace_secret_setup import valid_telegram_token, write_env_token


VALID_TOKEN = "123456789" + ":" + "AA" + "abcdefghijklmnopqrstuvwxyz_12345"


@pytest.mark.parametrize(
    "value",
    [
        VALID_TOKEN,
        "9876543210" + ":" + "ABCDEFGHIJKLMNOPQRSTUVWXYZ-abcdefghi",
    ],
)
def test_valid_telegram_token_accepts_botfather_shape(value: str) -> None:
    assert valid_telegram_token(value)


@pytest.mark.parametrize(
    "value",
    ["", "@my_bot", "token without colon", "123:too_short", "123456:has space"],
)
def test_valid_telegram_token_rejects_invalid_values(value: str) -> None:
    assert not valid_telegram_token(value)


def test_write_env_token_replaces_duplicates_and_preserves_other_keys(
    tmp_path: Path,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "AAQTS_EXECUTION_MODE=PAPER\n"
        "TELEGRAM_BOT_TOKEN="
        + "123456"
        + ":"
        + "old_token_value_that_is_long_enough\n"
        + "TELEGRAM_BOT_TOKEN="
        + "123456"
        + ":"
        + "another_old_token_value_long_enough\n",
        encoding="utf-8",
    )

    write_env_token(env_file, VALID_TOKEN)

    contents = env_file.read_text(encoding="utf-8")
    assert "AAQTS_EXECUTION_MODE=PAPER" in contents
    assert contents.count("TELEGRAM_BOT_TOKEN=") == 1
    assert f"TELEGRAM_BOT_TOKEN={VALID_TOKEN}" in contents
    if os.name == "posix":
        assert env_file.stat().st_mode & 0o777 == 0o600


def test_write_env_token_rejects_invalid_value(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Invalid Telegram bot token format"):
        write_env_token(tmp_path / ".env", "not-a-token")
