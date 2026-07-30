"""Typed models shared across the AAQTS AI decision layer."""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


@dataclass(frozen=True, slots=True)
class AIFeatureVector:
    """Deterministic market context consumed by downstream AI modules."""

    symbol: str
    timeframe: str
    signal: str
    score: float
    confidence_hint: float
    trade_quality: float
    trade_quality_approved: bool
    regime: str
    regime_confidence: float
    regime_direction: str
    adx: float
    rsi: float
    stoch_rsi: float
    macd: float
    macd_signal: float
    atr: float
    atr_percent: float
    close: float
    ema_20: float
    ema_50: float
    ema_200: float
    supertrend_bullish: bool
    trend_score: float
    momentum_score: float
    candle_score: float
    volume_score: float
    structure_score: float
    bullish_confirmations: int
    bearish_confirmations: int
    mtf_confirmed: bool
    reasons: List[str] = field(default_factory=list)
    generated_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["generated_at"] = self.generated_at.isoformat()
        return payload


@dataclass(frozen=True, slots=True)
class ConfidenceAssessment:
    score: float
    approved: bool
    reasons: List[str] = field(default_factory=list)
    model_name: Optional[str] = None


@dataclass(frozen=True, slots=True)
class TradeCritique:
    approved: bool
    severity: str
    warnings: List[str] = field(default_factory=list)
    confidence_adjustment: float = 0.0
