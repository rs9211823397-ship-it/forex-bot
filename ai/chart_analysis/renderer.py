from __future__ import annotations

import math
from pathlib import Path

import pandas as pd


class ChartRenderError(RuntimeError):
    """Raised when a causal chart cannot be rendered safely."""


def _finite(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _series_points(frame: pd.DataFrame, name: str) -> list[float | None]:
    if name not in frame.columns:
        return [None] * len(frame)
    return [_finite(item) for item in frame[name].tolist()]


class ChartRenderer:
    """Render deterministic, dependency-light OHLC charts for vision analysis."""

    def __init__(self, width: int = 1280, height: int = 720) -> None:
        self.width = int(width)
        self.height = int(height)
        if self.width < 640 or self.height < 360:
            raise ValueError("AI chart render dimensions are too small")

    @staticmethod
    def _pillow():
        try:
            from PIL import Image, ImageDraw, ImageFont
        except ImportError as exc:
            raise ChartRenderError(
                "Pillow is required for AI chart rendering; install requirements-ai.txt"
            ) from exc
        return Image, ImageDraw, ImageFont

    def render(
        self,
        frame: pd.DataFrame,
        *,
        symbol: str,
        timeframe: str,
        as_of_utc: str,
        output_path: str | Path,
    ) -> Path:
        required = {"open", "high", "low", "close"}
        missing = required.difference(frame.columns)
        if missing:
            raise ChartRenderError(
                "Chart frame missing OHLC columns: " + ", ".join(sorted(missing))
            )
        working = frame.copy()
        for column in required:
            working[column] = pd.to_numeric(working[column], errors="coerce")
        working = working.dropna(subset=sorted(required))
        if len(working) < 8:
            raise ChartRenderError("At least 8 completed candles are required to render a chart")

        Image, ImageDraw, ImageFont = self._pillow()
        image = Image.new("RGB", (self.width, self.height), (15, 18, 24))
        draw = ImageDraw.Draw(image)
        try:
            font = ImageFont.load_default()
        except Exception:
            font = None

        left, right = 72, self.width - 28
        top, bottom = 58, self.height - 92
        chart_width = max(1, right - left)
        chart_height = max(1, bottom - top)

        lows = pd.to_numeric(working["low"], errors="coerce")
        highs = pd.to_numeric(working["high"], errors="coerce")
        overlay_names = ("EMA_20", "EMA_50", "EMA_200", "BB_UPPER", "BB_LOWER")
        overlay_values: list[float] = []
        for name in overlay_names:
            if name in working.columns:
                overlay_values.extend(
                    value
                    for value in (_finite(item) for item in working[name].tolist())
                    if value is not None
                )

        price_min = float(lows.min())
        price_max = float(highs.max())
        if overlay_values:
            price_min = min(price_min, min(overlay_values))
            price_max = max(price_max, max(overlay_values))
        span = price_max - price_min
        if span <= 0:
            span = max(abs(price_max) * 0.001, 1e-6)
        pad = span * 0.06
        price_min -= pad
        price_max += pad
        span = price_max - price_min

        def y_of(price: float) -> float:
            return bottom - ((price - price_min) / span) * chart_height

        title = f"AAQTS {symbol} | {timeframe} | completed through {as_of_utc}"
        draw.text((left, 18), title, fill=(230, 233, 238), font=font)

        for step in range(6):
            ratio = step / 5
            y = top + ratio * chart_height
            price = price_max - ratio * span
            draw.line((left, y, right, y), fill=(42, 47, 57), width=1)
            draw.text((6, y - 6), f"{price:.6g}", fill=(160, 166, 178), font=font)

        count = len(working)
        slot = chart_width / max(count, 1)
        body_half = max(1.5, min(7.0, slot * 0.28))

        for i, (_, row) in enumerate(working.iterrows()):
            x = left + (i + 0.5) * slot
            open_price = float(row["open"])
            high_price = float(row["high"])
            low_price = float(row["low"])
            close_price = float(row["close"])
            rising = close_price >= open_price
            color = (51, 190, 130) if rising else (225, 85, 92)
            draw.line((x, y_of(high_price), x, y_of(low_price)), fill=color, width=1)
            y_open = y_of(open_price)
            y_close = y_of(close_price)
            body_top = min(y_open, y_close)
            body_bottom = max(y_open, y_close)
            if body_bottom - body_top < 1:
                body_bottom = body_top + 1
            draw.rectangle(
                (x - body_half, body_top, x + body_half, body_bottom),
                fill=color,
                outline=color,
            )

        overlay_styles = {
            "EMA_20": (241, 196, 15),
            "EMA_50": (68, 138, 255),
            "EMA_200": (192, 116, 255),
            "BB_UPPER": (130, 137, 151),
            "BB_LOWER": (130, 137, 151),
        }
        legend_x = left
        for name, color in overlay_styles.items():
            values = _series_points(working, name)
            points = []
            for i, value in enumerate(values):
                if value is None:
                    if len(points) > 1:
                        draw.line(points, fill=color, width=2)
                    points = []
                    continue
                points.append((left + (i + 0.5) * slot, y_of(value)))
            if len(points) > 1:
                draw.line(points, fill=color, width=2)
            if any(value is not None for value in values):
                draw.text((legend_x, bottom + 12), name, fill=color, font=font)
                legend_x += 82

        latest = working.iloc[-1]
        diagnostics: list[str] = []
        for name in ("RSI", "ADX", "ATR"):
            value = _finite(latest.get(name))
            if value is not None:
                diagnostics.append(f"{name}={value:.2f}")
        if "SUPERTREND" in working.columns:
            diagnostics.append(
                "SUPERTREND=" + ("BULL" if bool(latest.get("SUPERTREND")) else "BEAR")
            )
        if diagnostics:
            draw.text(
                (left, self.height - 36),
                " | ".join(diagnostics),
                fill=(190, 196, 207),
                font=font,
            )

        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        image.save(output, format="PNG", optimize=True)
        return output
