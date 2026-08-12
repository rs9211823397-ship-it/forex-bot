from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return bool(default)
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be true or false")


def _bounded_int(name: str, default: int, lower: int, upper: int) -> int:
    value = int(os.getenv(name, str(default)))
    if value < lower or value > upper:
        raise ValueError(f"{name} must be between {lower} and {upper}")
    return value


def _bounded_float(name: str, default: float, lower: float, upper: float) -> float:
    value = float(os.getenv(name, str(default)))
    if value < lower or value > upper:
        raise ValueError(f"{name} must be between {lower} and {upper}")
    return value


def _horizons(name: str, default: tuple[int, ...]) -> tuple[int, ...]:
    raw = os.getenv(name)
    if raw is None:
        return default
    values = tuple(int(item.strip()) for item in raw.split(",") if item.strip())
    if not values:
        raise ValueError(f"{name} must contain at least one positive integer")
    if any(item <= 0 or item > 96 for item in values):
        raise ValueError(f"{name} values must be between 1 and 96")
    if tuple(sorted(set(values))) != values:
        raise ValueError(f"{name} values must be unique and strictly increasing")
    return values


@dataclass(frozen=True)
class ChartObserverConfig:
    """Configuration for the non-executing Phase AI-1 observer."""

    enabled: bool = False
    remote_enabled: bool = False
    mode: str = "OBSERVER"
    model: str = "gpt-5"
    output_root: Path = Path("runtime/ai_chart_analysis")
    only_actionable: bool = True
    max_inflight: int = 2
    lower_render_bars: int = 96
    higher_render_bars: int = 96
    numeric_bars: int = 24
    timeout_seconds: float = 30.0
    image_detail: str = "high"
    max_output_tokens: int = 1400
    prompt_version: str = "aaqts_chart_v1.0"
    schema_version: str = "1.0"
    api_key_env: str = "OPENAI_API_KEY"
    endpoint: str = "https://api.openai.com/v1/responses"
    outcomes_enabled: bool = True
    outcome_horizons: tuple[int, ...] = (1, 3, 6, 12)
    outcome_stop_r: float = 1.0
    outcome_target_r: float = 2.0
    analytics_enabled: bool = True
    analytics_min_finalized_samples: int = 30
    analytics_min_bucket_samples: int = 10

    @classmethod
    def from_env(cls) -> "ChartObserverConfig":
        mode = os.getenv("AAQTS_AI_CHART_MODE", "OBSERVER").upper().strip()
        if mode != "OBSERVER":
            raise ValueError(
                "Phase AI-1 only supports AAQTS_AI_CHART_MODE=OBSERVER"
            )
        detail = os.getenv("AAQTS_AI_CHART_IMAGE_DETAIL", "high").lower().strip()
        if detail not in {"low", "high", "auto"}:
            raise ValueError(
                "AAQTS_AI_CHART_IMAGE_DETAIL must be low, high, or auto"
            )
        model = os.getenv("AAQTS_AI_CHART_MODEL", "gpt-5").strip()
        if not model:
            raise ValueError("AAQTS_AI_CHART_MODEL cannot be blank")
        endpoint = os.getenv(
            "AAQTS_AI_CHART_ENDPOINT",
            "https://api.openai.com/v1/responses",
        ).strip()
        if not endpoint.startswith("https://"):
            raise ValueError("AAQTS_AI_CHART_ENDPOINT must use https://")
        return cls(
            enabled=_flag("AAQTS_AI_CHART_ENABLED", False),
            remote_enabled=_flag("AAQTS_AI_CHART_REMOTE_ENABLED", False),
            mode=mode,
            model=model,
            output_root=Path(
                os.getenv(
                    "AAQTS_AI_CHART_OUTPUT_ROOT",
                    "runtime/ai_chart_analysis",
                ).strip()
                or "runtime/ai_chart_analysis"
            ),
            only_actionable=_flag(
                "AAQTS_AI_CHART_ONLY_ACTIONABLE",
                True,
            ),
            max_inflight=_bounded_int(
                "AAQTS_AI_CHART_MAX_INFLIGHT", 2, 1, 8
            ),
            lower_render_bars=_bounded_int(
                "AAQTS_AI_CHART_LOWER_RENDER_BARS", 96, 32, 240
            ),
            higher_render_bars=_bounded_int(
                "AAQTS_AI_CHART_HIGHER_RENDER_BARS", 96, 32, 240
            ),
            numeric_bars=_bounded_int(
                "AAQTS_AI_CHART_NUMERIC_BARS", 24, 8, 64
            ),
            timeout_seconds=_bounded_float(
                "AAQTS_AI_CHART_TIMEOUT_SECONDS", 30.0, 5.0, 120.0
            ),
            image_detail=detail,
            max_output_tokens=_bounded_int(
                "AAQTS_AI_CHART_MAX_OUTPUT_TOKENS", 1400, 400, 4000
            ),
            prompt_version=os.getenv(
                "AAQTS_AI_CHART_PROMPT_VERSION",
                "aaqts_chart_v1.0",
            ).strip()
            or "aaqts_chart_v1.0",
            schema_version="1.0",
            api_key_env=os.getenv(
                "AAQTS_AI_CHART_API_KEY_ENV",
                "OPENAI_API_KEY",
            ).strip()
            or "OPENAI_API_KEY",
            endpoint=endpoint,
            outcomes_enabled=_flag("AAQTS_AI_CHART_OUTCOMES_ENABLED", True),
            outcome_horizons=_horizons(
                "AAQTS_AI_CHART_OUTCOME_HORIZONS",
                (1, 3, 6, 12),
            ),
            outcome_stop_r=_bounded_float(
                "AAQTS_AI_CHART_OUTCOME_STOP_R", 1.0, 0.25, 5.0
            ),
            outcome_target_r=_bounded_float(
                "AAQTS_AI_CHART_OUTCOME_TARGET_R", 2.0, 0.25, 10.0
            ),
            analytics_enabled=_flag("AAQTS_AI_CHART_ANALYTICS_ENABLED", True),
            analytics_min_finalized_samples=_bounded_int(
                "AAQTS_AI_CHART_ANALYTICS_MIN_FINALIZED", 30, 1, 10000
            ),
            analytics_min_bucket_samples=_bounded_int(
                "AAQTS_AI_CHART_ANALYTICS_MIN_BUCKET", 10, 1, 10000
            ),
        )
