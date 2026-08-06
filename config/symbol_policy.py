"""Runtime symbol enable/disable policy.

This layer sits above the authoritative catalog. It lets operators temporarily
remove otherwise supported broker instruments from both analysis and execution
without deleting catalog metadata or changing the strategy implementation.
"""

from __future__ import annotations

from collections.abc import Iterable

from config.symbols import SYMBOL_CATALOG, symbol_by_broker


DEFAULT_DISABLED_BROKER_SYMBOLS: tuple[str, ...] = (
    "XAUUSD",
    "XAGUSD",
    "XPTUSD",
    "XPDUSD",
)


def parse_disabled_broker_symbols(value: str | None) -> tuple[str, ...]:
    """Parse a comma-separated broker-symbol list and validate catalog names."""
    if value is None:
        return DEFAULT_DISABLED_BROKER_SYMBOLS
    disabled = tuple(
        sorted(
            {
                token.strip().upper()
                for token in str(value).split(",")
                if token.strip()
            }
        )
    )
    for broker_symbol in disabled:
        symbol_by_broker(broker_symbol)
    return disabled


def disabled_data_symbols(disabled_broker_symbols: Iterable[str]) -> set[str]:
    """Translate disabled broker symbols to their market-data identifiers."""
    result: set[str] = set()
    for broker_symbol in disabled_broker_symbols:
        definition = symbol_by_broker(str(broker_symbol))
        if definition.data_symbol:
            result.add(definition.data_symbol)
    return result


def filter_active_symbols(
    grouped: dict[str, list[str]],
    disabled_broker_symbols: Iterable[str],
) -> dict[str, list[str]]:
    """Return a copy of active symbol groups without temporarily disabled names."""
    blocked = disabled_data_symbols(disabled_broker_symbols)
    return {
        category: [symbol for symbol in symbols if symbol not in blocked]
        for category, symbols in grouped.items()
    }


def filter_executable_map(
    mapping: dict[str, str],
    disabled_broker_symbols: Iterable[str],
) -> dict[str, str]:
    """Remove disabled broker instruments from executable source->broker map."""
    disabled = {str(symbol).strip().upper() for symbol in disabled_broker_symbols}
    return {
        source: broker
        for source, broker in mapping.items()
        if str(broker).strip().upper() not in disabled
    }


__all__ = [
    "DEFAULT_DISABLED_BROKER_SYMBOLS",
    "disabled_data_symbols",
    "filter_active_symbols",
    "filter_executable_map",
    "parse_disabled_broker_symbols",
]
