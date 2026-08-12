from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

MARKET_REGIMES = {"TREND", "RANGE", "BREAKOUT", "TRANSITION", "UNKNOWN"}
DIRECTIONS = {"BULLISH", "BEARISH", "NEUTRAL", "UNKNOWN"}
MARKET_STRUCTURES = {"BULLISH", "BEARISH", "RANGE", "MIXED", "UNKNOWN"}
STRUCTURE_EVENTS = {"BOS", "CHOCH", "NONE", "UNKNOWN"}
LIQUIDITY_EVENTS = {
    "BUY_SIDE_SWEEP",
    "SELL_SIDE_SWEEP",
    "BOTH",
    "NONE",
    "UNKNOWN",
}
SETUPS = {
    "PULLBACK_CONTINUATION",
    "BREAKOUT_CONTINUATION",
    "REVERSAL",
    "RANGE_REVERSION",
    "LIQUIDITY_REVERSAL",
    "NO_SETUP",
    "UNKNOWN",
}
SIGNALS = {"BUY", "SELL", "HOLD"}
DATA_QUALITY = {"GOOD", "DEGRADED", "INSUFFICIENT"}

ANALYSIS_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "schema_version": {"type": "string"},
        "snapshot_id": {"type": "string"},
        "symbol": {"type": "string"},
        "as_of_utc": {"type": "string"},
        "market_regime": {"type": "string", "enum": sorted(MARKET_REGIMES)},
        "trend_direction": {"type": "string", "enum": sorted(DIRECTIONS)},
        "higher_timeframe_bias": {"type": "string", "enum": sorted(DIRECTIONS)},
        "market_structure": {"type": "string", "enum": sorted(MARKET_STRUCTURES)},
        "structure_event": {"type": "string", "enum": sorted(STRUCTURE_EVENTS)},
        "liquidity_event": {"type": "string", "enum": sorted(LIQUIDITY_EVENTS)},
        "setup": {"type": "string", "enum": sorted(SETUPS)},
        "signal": {"type": "string", "enum": sorted(SIGNALS)},
        "confidence": {"type": "number"},
        "entry_zone_low": {"type": ["number", "null"]},
        "entry_zone_high": {"type": ["number", "null"]},
        "invalidation_price": {"type": ["number", "null"]},
        "target_1": {"type": ["number", "null"]},
        "target_2": {"type": ["number", "null"]},
        "estimated_rr": {"type": ["number", "null"]},
        "evidence": {"type": "array", "items": {"type": "string"}},
        "contradictions": {"type": "array", "items": {"type": "string"}},
        "data_quality": {"type": "string", "enum": sorted(DATA_QUALITY)},
        "abstain": {"type": "boolean"},
    },
    "required": [
        "schema_version",
        "snapshot_id",
        "symbol",
        "as_of_utc",
        "market_regime",
        "trend_direction",
        "higher_timeframe_bias",
        "market_structure",
        "structure_event",
        "liquidity_event",
        "setup",
        "signal",
        "confidence",
        "entry_zone_low",
        "entry_zone_high",
        "invalidation_price",
        "target_1",
        "target_2",
        "estimated_rr",
        "evidence",
        "contradictions",
        "data_quality",
        "abstain",
    ],
}


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("as_of_utc must include a timezone")
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class ChartAnalysis:
    schema_version: str
    snapshot_id: str
    symbol: str
    as_of_utc: str
    market_regime: str
    trend_direction: str
    higher_timeframe_bias: str
    market_structure: str
    structure_event: str
    liquidity_event: str
    setup: str
    signal: str
    confidence: float
    entry_zone_low: float | None
    entry_zone_high: float | None
    invalidation_price: float | None
    target_1: float | None
    target_2: float | None
    estimated_rr: float | None
    evidence: tuple[str, ...]
    contradictions: tuple[str, ...]
    data_quality: str
    abstain: bool

    @classmethod
    def from_payload(
        cls,
        payload: dict[str, Any],
        *,
        expected_snapshot_id: str,
        expected_symbol: str,
        expected_as_of_utc: str,
        expected_schema_version: str = "1.0",
    ) -> "ChartAnalysis":
        expected_fields = set(ANALYSIS_JSON_SCHEMA["required"])
        if set(payload) != expected_fields:
            missing = expected_fields.difference(payload)
            extra = set(payload).difference(expected_fields)
            raise ValueError(
                "AI chart payload fields mismatch; "
                f"missing={sorted(missing)} extra={sorted(extra)}"
            )
        if str(payload["schema_version"]) != expected_schema_version:
            raise ValueError("AI chart schema_version mismatch")
        if str(payload["snapshot_id"]) != expected_snapshot_id:
            raise ValueError("AI chart snapshot_id mismatch")
        if str(payload["symbol"]) != expected_symbol:
            raise ValueError("AI chart symbol mismatch")
        if _utc(str(payload["as_of_utc"])) != _utc(expected_as_of_utc):
            raise ValueError("AI chart as_of_utc mismatch")

        confidence = float(payload["confidence"])
        if confidence < 0 or confidence > 100:
            raise ValueError("AI chart confidence must be between 0 and 100")

        enum_checks = (
            ("market_regime", MARKET_REGIMES),
            ("trend_direction", DIRECTIONS),
            ("higher_timeframe_bias", DIRECTIONS),
            ("market_structure", MARKET_STRUCTURES),
            ("structure_event", STRUCTURE_EVENTS),
            ("liquidity_event", LIQUIDITY_EVENTS),
            ("setup", SETUPS),
            ("signal", SIGNALS),
            ("data_quality", DATA_QUALITY),
        )
        for field, allowed in enum_checks:
            if str(payload[field]) not in allowed:
                raise ValueError(f"Invalid {field}: {payload[field]}")

        def optional_float(name: str) -> float | None:
            value = payload[name]
            return None if value is None else float(value)

        evidence = tuple(
            str(item).strip()
            for item in payload["evidence"]
            if str(item).strip()
        )
        contradictions = tuple(
            str(item).strip()
            for item in payload["contradictions"]
            if str(item).strip()
        )

        return cls(
            schema_version=str(payload["schema_version"]),
            snapshot_id=str(payload["snapshot_id"]),
            symbol=str(payload["symbol"]),
            as_of_utc=_utc(str(payload["as_of_utc"])).isoformat(),
            market_regime=str(payload["market_regime"]),
            trend_direction=str(payload["trend_direction"]),
            higher_timeframe_bias=str(payload["higher_timeframe_bias"]),
            market_structure=str(payload["market_structure"]),
            structure_event=str(payload["structure_event"]),
            liquidity_event=str(payload["liquidity_event"]),
            setup=str(payload["setup"]),
            signal=str(payload["signal"]),
            confidence=confidence,
            entry_zone_low=optional_float("entry_zone_low"),
            entry_zone_high=optional_float("entry_zone_high"),
            invalidation_price=optional_float("invalidation_price"),
            target_1=optional_float("target_1"),
            target_2=optional_float("target_2"),
            estimated_rr=optional_float("estimated_rr"),
            evidence=evidence,
            contradictions=contradictions,
            data_quality=str(payload["data_quality"]),
            abstain=bool(payload["abstain"]),
        )

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["evidence"] = list(self.evidence)
        result["contradictions"] = list(self.contradictions)
        return result
