from __future__ import annotations

from typing import Any


class AIDecisionAnalyzer:
    """Create a structured report for AAQTS trading decisions."""

    def analyze(
        self,
        *,
        signal: str,
        confidence: float | int,
        score: float | int,
        reasons: list[str] | tuple[str, ...] | None = None,
        decision_summary: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized_signal = str(signal or "HOLD").upper().strip()
        reasons_list = [str(reason).strip() for reason in (reasons or []) if str(reason).strip()]
        decision_summary = decision_summary or {}
        positive_factors = [
            str(item).strip()
            for item in decision_summary.get("positive", []) or []
            if str(item).strip()
        ]
        warning_factors = [
            str(item).strip()
            for item in decision_summary.get("warnings", []) or []
            if str(item).strip()
        ]

        rejection_reasons = []
        seen = set()

        for reason in reasons_list + warning_factors:
            if self._is_rejection_reason(reason) and reason not in seen:
                rejection_reasons.append(reason)
                seen.add(reason)

        if normalized_signal == "HOLD" and not rejection_reasons:
            rejection_reasons.append("Signal was held by the engine")

        approved = normalized_signal != "HOLD" and not rejection_reasons

        return {
            "decision": normalized_signal,
            "status": "APPROVED" if approved else "REJECTED",
            "approved": approved,
            "confidence": float(confidence or 0),
            "score": float(score or 0),
            "reasons": reasons_list,
            "decision_summary": {
                "positive": positive_factors,
                "warnings": warning_factors,
            },
            "rejection_reasons": rejection_reasons,
        }

    def format_report(self, report: dict[str, Any]) -> str:
        decision = str(report.get("decision", "HOLD")).upper().strip()
        status = str(report.get("status", "REJECTED")).upper().strip()
        confidence = report.get("confidence", 0)
        score = report.get("score", 0)
        rejection_reasons = report.get("rejection_reasons") or []
        positive_factors = (report.get("decision_summary") or {}).get("positive", []) or []

        lines = [
            f"Decision: {decision}",
            f"Status: {status}",
            f"Confidence: {confidence:.0f}%",
            f"Score: {score}",
        ]

        if positive_factors:
            lines.append("Positive factors:")
            lines.extend([f"- {factor}" for factor in positive_factors])

        if rejection_reasons:
            lines.append("Rejection reasons:")
            lines.extend([f"- {reason}" for reason in rejection_reasons])

        return "\n".join(lines)

    @staticmethod
    def _is_rejection_reason(reason: str) -> bool:
        text = reason.lower()
        if not text:
            return False
        rejected_markers = (
            "weak",
            "conflicts",
            "blocks",
            "not confirmed",
            "insufficient",
            "trade quality",
            "unknown",
            "reject",
            "error",
            "hold",
            "no directional",
            "low-volatility",
            "high-volatility",
            "unstructured",
        )
        return any(marker in text for marker in rejected_markers)
