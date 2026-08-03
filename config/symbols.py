"""Authoritative market-data and Exness/MT5 symbol catalog.

The catalog deliberately separates being known from being enabled.  A symbol
is enabled only when the current Yahoo research feed and USD-account risk
accounting can support it safely.  Broker close-only or unavailable symbols
remain visible without being eligible for new AAQTS entries.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


EntryPolicy = Literal["OPEN", "CLOSE_ONLY", "UNAVAILABLE", "PAPER_ONLY"]


@dataclass(frozen=True)
class SymbolDefinition:
    broker_symbol: str
    category: str
    base_asset: str
    quote_asset: str
    data_symbol: str | None
    entry_policy: EntryPolicy = "OPEN"
    enabled_by_default: bool = False
    disabled_reason: str = ""

    def __post_init__(self) -> None:
        broker = self.broker_symbol.strip().upper()
        category = self.category.strip().lower()
        base = self.base_asset.strip().upper()
        quote = self.quote_asset.strip().upper()
        if not broker or category not in {"forex", "metals", "crypto"}:
            raise ValueError("Invalid symbol definition")
        if not base or not quote or base == quote:
            raise ValueError("Symbol assets must be distinct and non-empty")
        if self.entry_policy != "OPEN" and self.enabled_by_default:
            raise ValueError("Non-open symbols cannot be enabled by default")
        if self.enabled_by_default and not self.data_symbol:
            raise ValueError("Enabled symbols require a market-data symbol")
        object.__setattr__(self, "broker_symbol", broker)
        object.__setattr__(self, "category", category)
        object.__setattr__(self, "base_asset", base)
        object.__setattr__(self, "quote_asset", quote)


def _symbol(
    broker_symbol: str,
    category: str,
    base_asset: str,
    quote_asset: str,
    data_symbol: str | None,
    *,
    enabled: bool = False,
    policy: EntryPolicy = "OPEN",
    reason: str = "",
) -> SymbolDefinition:
    return SymbolDefinition(
        broker_symbol=broker_symbol,
        category=category,
        base_asset=base_asset,
        quote_asset=quote_asset,
        data_symbol=data_symbol,
        entry_policy=policy,
        enabled_by_default=enabled,
        disabled_reason=reason,
    )


SYMBOL_CATALOG: tuple[SymbolDefinition, ...] = (
    # Seven Forex majors. Yahoo uses short USD-base tickers for JPY/CHF/CAD.
    _symbol("EURUSD", "forex", "EUR", "USD", "EURUSD=X", enabled=True),
    _symbol("GBPUSD", "forex", "GBP", "USD", "GBPUSD=X", enabled=True),
    _symbol("USDJPY", "forex", "USD", "JPY", "JPY=X", enabled=True),
    _symbol("USDCHF", "forex", "USD", "CHF", "CHF=X", enabled=True),
    _symbol("USDCAD", "forex", "USD", "CAD", "CAD=X", enabled=True),
    _symbol("AUDUSD", "forex", "AUD", "USD", "AUDUSD=X", enabled=True),
    _symbol("NZDUSD", "forex", "NZD", "USD", "NZDUSD=X", enabled=True),

    # USD metals can use the existing futures research feed safely. Crosses
    # stay catalogued until synchronized spot data and quote-currency account
    # conversion are implemented.
    _symbol("XAUUSD", "metals", "XAU", "USD", "GC=F", enabled=True),
    _symbol(
        "XAUEUR", "metals", "XAU", "EUR", None,
        reason="Requires synchronized spot-gold data and EUR-to-USD P/L conversion",
    ),
    _symbol(
        "XAUGBP", "metals", "XAU", "GBP", None,
        reason="Requires synchronized spot-gold data and GBP-to-USD P/L conversion",
    ),
    _symbol(
        "XAUAUD", "metals", "XAU", "AUD", None,
        reason="Requires synchronized spot-gold data and AUD-to-USD P/L conversion",
    ),
    _symbol("XAGUSD", "metals", "XAG", "USD", "SI=F", enabled=True),
    _symbol(
        "XAGEUR", "metals", "XAG", "EUR", None,
        reason="Requires synchronized spot-silver data and EUR-to-USD P/L conversion",
    ),
    _symbol(
        "XAGGBP", "metals", "XAG", "GBP", None,
        reason="Requires synchronized spot-silver data and GBP-to-USD P/L conversion",
    ),
    _symbol(
        "XAGAUD", "metals", "XAG", "AUD", None,
        reason="Requires synchronized spot-silver data and AUD-to-USD P/L conversion",
    ),
    _symbol("XPTUSD", "metals", "XPT", "USD", "PL=F", enabled=True),
    _symbol("XPDUSD", "metals", "XPD", "USD", "PA=F", enabled=True),

    # Open Exness crypto instruments with a USD/USDT-compatible research
    # quote are enabled. Non-USD crosses remain disabled until account-currency
    # conversion is part of paper/backtest accounting.
    _symbol("BTCUSD", "crypto", "BTC", "USD", "BTC-USD", enabled=True),
    _symbol("ETHUSD", "crypto", "ETH", "USD", "ETH-USD", enabled=True),
    _symbol(
        "BTCUSDT", "crypto", "BTC", "USDT", None,
        reason="Requires broker-native BTCUSDT candles; BTCUSD is not an exact proxy",
    ),
    _symbol(
        "ETHBTC", "crypto", "ETH", "BTC", "ETH-BTC",
        reason="Requires BTC-to-USD P/L conversion",
    ),
    _symbol(
        "BTCJPY", "crypto", "BTC", "JPY", "BTC-JPY",
        reason="Requires JPY-to-USD P/L conversion",
    ),
    _symbol(
        "BTCKRW", "crypto", "BTC", "KRW", "BTC-KRW",
        policy="UNAVAILABLE",
        reason="Not listed in the current Exness cryptocurrency specification",
    ),
    _symbol(
        "BTCAUD", "crypto", "BTC", "AUD", None,
        policy="CLOSE_ONLY", reason="Exness currently permits closing only",
    ),
    _symbol(
        "BTCCNH", "crypto", "BTC", "CNH", None,
        policy="CLOSE_ONLY", reason="Exness currently permits closing only",
    ),
    _symbol(
        "BTCTHB", "crypto", "BTC", "THB", None,
        policy="CLOSE_ONLY", reason="Exness currently permits closing only",
    ),
    _symbol(
        "BTCZAR", "crypto", "BTC", "ZAR", None,
        policy="CLOSE_ONLY", reason="Exness currently permits closing only",
    ),
    _symbol(
        "BTCXAU", "crypto", "BTC", "XAU", None,
        policy="CLOSE_ONLY", reason="Exness currently permits closing only",
    ),
    _symbol(
        "BTCXAG", "crypto", "BTC", "XAG", None,
        policy="CLOSE_ONLY", reason="Exness currently permits closing only",
    ),

    # Existing research instrument retained for backward compatibility.
    _symbol(
        "SOLUSD", "crypto", "SOL", "USD", "SOL-USD",
        policy="PAPER_ONLY",
        reason="Retained for paper research; not in the current Exness specification",
    ),
)


def _validate_catalog() -> None:
    broker_symbols = [item.broker_symbol for item in SYMBOL_CATALOG]
    data_symbols = [item.data_symbol for item in SYMBOL_CATALOG if item.data_symbol]
    if len(broker_symbols) != len(set(broker_symbols)):
        raise ValueError("Duplicate broker symbol in catalog")
    if len(data_symbols) != len(set(data_symbols)):
        raise ValueError("Duplicate market-data symbol in catalog")
    for item in SYMBOL_CATALOG:
        if not item.enabled_by_default and not item.disabled_reason:
            raise ValueError(
                f"Disabled symbol {item.broker_symbol} requires a reason"
            )


_validate_catalog()


def symbol_by_broker(broker_symbol: str) -> SymbolDefinition:
    normalized = str(broker_symbol).strip().upper()
    for definition in SYMBOL_CATALOG:
        if definition.broker_symbol == normalized:
            return definition
    raise KeyError(f"Unknown broker symbol: {normalized}")


def symbol_by_data(data_symbol: str) -> SymbolDefinition:
    normalized = str(data_symbol).strip().upper()
    for definition in SYMBOL_CATALOG:
        if definition.data_symbol and definition.data_symbol.upper() == normalized:
            return definition
    raise KeyError(f"Unknown market-data symbol: {normalized}")


def active_symbols(*, include_paper_only: bool = True) -> dict[str, list[str]]:
    grouped = {"forex": [], "metals": [], "crypto": []}
    for definition in SYMBOL_CATALOG:
        if definition.enabled_by_default:
            assert definition.data_symbol is not None
            grouped[definition.category].append(definition.data_symbol)
    if include_paper_only:
        grouped["crypto"].append("SOL-USD")
    return grouped


def executable_symbol_map() -> dict[str, str]:
    return {
        definition.data_symbol: definition.broker_symbol
        for definition in SYMBOL_CATALOG
        if definition.data_symbol
        and definition.entry_policy == "OPEN"
        and definition.enabled_by_default
    }


__all__ = [
    "SYMBOL_CATALOG",
    "SymbolDefinition",
    "active_symbols",
    "executable_symbol_map",
    "symbol_by_broker",
    "symbol_by_data",
]
