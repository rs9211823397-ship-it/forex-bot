from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path
from typing import Any
from urllib import error, request

from .config import ChartObserverConfig
from .prompt import SYSTEM_PROMPT, build_user_prompt
from .schema import ANALYSIS_JSON_SCHEMA, ChartAnalysis
from .snapshot import MarketSnapshot


class ChartClientError(RuntimeError):
    """Raised when the remote chart-analysis request cannot be trusted."""


def _data_url(path: str | Path) -> str:
    data = Path(path).read_bytes()
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _extract_output_text(response: dict[str, Any]) -> str:
    for item in response.get("output", []) or []:
        if item.get("type") != "message":
            continue
        for content in item.get("content", []) or []:
            if content.get("type") == "output_text" and content.get("text"):
                return str(content["text"])
            if content.get("type") == "refusal":
                raise ChartClientError(
                    "AI chart request was refused: " + str(content.get("refusal", ""))
                )
    raise ChartClientError("Responses API returned no output_text")


class OpenAIResponsesChartClient:
    """Minimal Responses API client with strict schema validation."""

    def __init__(self, config: ChartObserverConfig) -> None:
        self.config = config

    def analyze(
        self,
        snapshot: MarketSnapshot,
        lower_image: str | Path,
        higher_image: str | Path,
    ) -> tuple[ChartAnalysis, dict[str, Any]]:
        api_key = os.getenv(self.config.api_key_env, "").strip()
        if not api_key:
            raise ChartClientError(
                f"Missing API key environment variable: {self.config.api_key_env}"
            )

        body = {
            "model": self.config.model,
            "instructions": SYSTEM_PROMPT,
            "input": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": build_user_prompt(snapshot),
                        },
                        {
                            "type": "input_image",
                            "image_url": _data_url(lower_image),
                            "detail": self.config.image_detail,
                        },
                        {
                            "type": "input_image",
                            "image_url": _data_url(higher_image),
                            "detail": self.config.image_detail,
                        },
                    ],
                }
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "aaqts_chart_analysis",
                    "description": "Independent AAQTS Phase AI-1 chart observation",
                    "schema": ANALYSIS_JSON_SCHEMA,
                    "strict": True,
                }
            },
            "max_output_tokens": self.config.max_output_tokens,
        }
        encoded = json.dumps(body, separators=(",", ":")).encode("utf-8")
        http_request = request.Request(
            self.config.endpoint,
            data=encoded,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "User-Agent": "AAQTS-ChartObserver/1.0",
            },
            method="POST",
        )

        started = time.perf_counter()
        try:
            with request.urlopen(
                http_request,
                timeout=self.config.timeout_seconds,
            ) as response:
                raw = response.read().decode("utf-8")
        except error.HTTPError as exc:
            try:
                detail = exc.read().decode("utf-8", errors="replace")[:1200]
            except Exception:
                detail = ""
            raise ChartClientError(
                f"Responses API HTTP {exc.code}: {detail or exc.reason}"
            ) from exc
        except (error.URLError, TimeoutError, OSError) as exc:
            raise ChartClientError(f"Responses API transport failure: {exc}") from exc
        latency_ms = (time.perf_counter() - started) * 1000.0

        try:
            response_payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ChartClientError("Responses API returned invalid JSON") from exc

        output_text = _extract_output_text(response_payload)
        try:
            payload = json.loads(output_text)
        except json.JSONDecodeError as exc:
            raise ChartClientError("Structured output_text is not valid JSON") from exc
        if not isinstance(payload, dict):
            raise ChartClientError("Structured output must be a JSON object")

        try:
            analysis = ChartAnalysis.from_payload(
                payload,
                expected_snapshot_id=snapshot.snapshot_id,
                expected_symbol=snapshot.symbol,
                expected_as_of_utc=snapshot.as_of_utc,
                expected_schema_version=snapshot.schema_version,
            )
        except (TypeError, ValueError) as exc:
            raise ChartClientError(f"Structured output validation failed: {exc}") from exc

        metadata = {
            "response_id": response_payload.get("id"),
            "model": response_payload.get("model", self.config.model),
            "status": response_payload.get("status"),
            "latency_ms": round(latency_ms, 3),
            "usage": response_payload.get("usage") or {},
        }
        return analysis, metadata
