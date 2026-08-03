"""Interfaces for a future trade-quality model.

The production default is deliberately disabled.  This module exposes only
quality ranking and allow/block decisions; it has no API capable of producing
a BUY or SELL signal.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
from typing import Protocol, runtime_checkable

from ai.features import FeatureSnapshot


class FilterAction(str, Enum):
    ALLOW = "ALLOW"
    BLOCK = "BLOCK"


@dataclass(frozen=True)
class QualityEstimate:
    """Model-supplied quality estimate for an existing setup."""

    score: float
    model_version: str

    def __post_init__(self):
        try:
            score = float(self.score)
        except (TypeError, ValueError) as exc:
            raise ValueError("Quality score must be numeric") from exc
        if not math.isfinite(score) or not 0.0 <= score <= 1.0:
            raise ValueError("Quality score must be between 0 and 1")
        object.__setattr__(self, "score", score)

        model_version = str(self.model_version).strip()
        if not model_version:
            raise ValueError("model_version cannot be empty")
        object.__setattr__(self, "model_version", model_version)


@runtime_checkable
class TradeQualityModel(Protocol):
    """Protocol implemented by a future, externally validated model."""

    def estimate(self, snapshot: FeatureSnapshot) -> QualityEstimate:
        """Rank an existing setup without creating a direction."""


@dataclass(frozen=True)
class FilterResult:
    """A direction-free result that can only allow or block a setup."""

    action: FilterAction
    enabled: bool
    quality_score: float | None
    model_version: str | None
    reasons: tuple[str, ...]


class TradeQualityFilter:
    """Optional post-rules quality gate.

    Disabled mode is the default and is a no-op.  Enabling requires both a
    concrete validated model and an explicit acceptance threshold, so this
    infrastructure cannot silently change production trading behavior.
    """

    def __init__(
        self,
        *,
        enabled: bool = False,
        model: TradeQualityModel | None = None,
        minimum_quality: float | None = None,
    ):
        self.enabled = bool(enabled)
        self.model = model
        self.minimum_quality = minimum_quality

        if self.enabled:
            if model is None or not isinstance(model, TradeQualityModel):
                raise ValueError(
                    "Enabled quality filtering requires a "
                    "TradeQualityModel"
                )
            if minimum_quality is None:
                raise ValueError(
                    "Enabled quality filtering requires an explicit "
                    "minimum_quality"
                )
            threshold = float(minimum_quality)
            if not math.isfinite(threshold) or not 0.0 <= threshold <= 1.0:
                raise ValueError(
                    "minimum_quality must be between 0 and 1"
                )
            self.minimum_quality = threshold

    def evaluate(self, snapshot: FeatureSnapshot) -> FilterResult:
        if not isinstance(snapshot, FeatureSnapshot):
            raise TypeError("snapshot must be a FeatureSnapshot")

        if not self.enabled:
            return FilterResult(
                action=FilterAction.ALLOW,
                enabled=False,
                quality_score=None,
                model_version=None,
                reasons=("trade_quality_filter_disabled",),
            )

        estimate = self.model.estimate(snapshot)
        if not isinstance(estimate, QualityEstimate):
            raise TypeError(
                "TradeQualityModel.estimate must return QualityEstimate"
            )

        if estimate.score >= self.minimum_quality:
            return FilterResult(
                action=FilterAction.ALLOW,
                enabled=True,
                quality_score=estimate.score,
                model_version=estimate.model_version,
                reasons=("quality_threshold_passed",),
            )

        return FilterResult(
            action=FilterAction.BLOCK,
            enabled=True,
            quality_score=estimate.score,
            model_version=estimate.model_version,
            reasons=("quality_threshold_failed",),
        )


__all__ = [
    "FilterAction",
    "FilterResult",
    "QualityEstimate",
    "TradeQualityFilter",
    "TradeQualityModel",
]
