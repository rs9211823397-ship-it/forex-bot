from __future__ import annotations

from typing import Any


class AIDecisionAnalyzer:
    """Create a structured report for AAQTS trading decisions.

    The formatter distinguishes a held candidate from an execution rejection.
    It also avoids presenting directionally-opposed evidence as a positive
    factor and surfaces one primary blocker before secondary observations.
    """

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
        numeric_score = float(score or 0)
        candidate_direction = (
            normalized_signal
            if normalized_signal in {"BUY", "SELL"}
            else "BUY" if numeric_score > 0 else "SELL" if numeric_score < 0 else None
        )
        reasons_list = [
            str(reason).strip()
            for reason in (reasons or [])
            if str(reason).strip()
        ]
        decision_summary = decision_summary or {}

        raw_positive = [
            str(item).strip()
            for item in decision_summary.get("positive", []) or []
            if str(item).strip()
        ]
        positive_factors = self._directionally_consistent(
            raw_positive,
            candidate_direction,
        )

        warning_factors = [
            str(item).strip()
            for item in decision_summary.get("warnings", []) or []
            if str(item).strip()
        ]

        blockers = []
        seen = set()
        for reason in reasons_list + warning_factors:
            if self._is_blocker(reason) and reason not in seen:
                blockers.append(reason)
                seen.add(reason)

        if normalized_signal == "HOLD" and not blockers:
            blockers.append("No actionable setup passed the complete decision policy")

        primary_reason = self._primary_reason(blockers)
        secondary_reasons = [reason for reason in blockers if reason != primary_reason]
        approved = normalized_signal in {"BUY", "SELL"}

        return {
            "decision": normalized_signal,
            "candidate_direction": candidate_direction,
            "status": "APPROVED" if approved else "HELD",
            "approved": approved,
            "confidence": float(confidence or 0),
            "score": numeric_score,
            "reasons": reasons_list,
            "decision_summary": {
                "positive": positive_factors,
                "warnings": warning_factors,
            },
            "primary_reason": primary_reason,
            "rejection_reasons": blockers,
            "secondary_reasons": secondary_reasons,
        }

    def format_report(self, report: dict[str, Any]) -> str:
        decision = str(report.get("decision", "HOLD")).upper().strip()
        status = str(report.get("status", "HELD")).upper().strip()
        confidence = float(report.get("confidence", 0) or 0)
        score = float(report.get("score", 0) or 0)
        primary_reason = report.get("primary_reason")
        secondary = report.get("secondary_reasons") or []
        positive_factors = (report.get("decision_summary") or {}).get("positive", []) or []
        candidate = report.get("candidate_direction")

        lines = [
            f"Decision: {decision}",
            f"Status: {status}",
            f"Trade quality: {confidence:.0f}/100",
            f"Directional score: {score:+.0f}",
        ]

        if decision == "HOLD" and candidate:
            lines.append(f"Candidate bias: {candidate}")

        if primary_reason:
            lines.append(f"Primary blocker: {self._clean_reason(primary_reason)}")

        if positive_factors:
            lines.append("Supporting evidence:")
            lines.extend([f"- {factor}" for factor in positive_factors[:4]])

        if secondary:
            lines.append("Secondary cautions:")
            lines.extend([f"- {self._clean_reason(reason)}" for reason in secondary[:3]])

        return "\n".join(lines)

    @classmethod
    def _primary_reason(cls, reasons: list[str]) -> str | None:
        if not reasons:
            return None
        priorities = (
            "Rejected:",
            "blocks",
            "conflicts",
            "No directional setup",
            "Contextual INVALID_LOCATION",
            "NO_CONTEXTUAL_TRIGGER",
            "Regime confidence below",
            "Weak momentum",
            "Weak volume",
        )
        for marker in priorities:
            for reason in reasons:
                if marker.lower() in reason.lower():
                    return reason
        return reasons[0]

    @staticmethod
    def _clean_reason(reason: str) -> str:
        text = str(reason).strip()
        if text.lower().startswith("rejected:"):
            return text.split(":", 1)[1].strip()
        return text

    @staticmethod
    def _directionally_consistent(
        factors: list[str],
        candidate_direction: str | None,
    ) -> list[str]:
        if candidate_direction is None:
            return factors
        result = []
        for factor in factors:
            lower = factor.lower()
            if candidate_direction == "BUY" and "bearish" in lower:
                continue
            if candidate_direction == "SELL" and "bullish" in lower:
                continue
            if factor not in result:
                result.append(factor)
        return result

    @staticmethod
    def _is_blocker(reason: str) -> bool:
        text = reason.lower().strip()
        if not text:
            return False

        # Trade quality is descriptive on its own; it becomes a blocker only
        # when the strategy explicitly reports that the threshold was not met.
        if text.startswith("trade quality:"):
            return False

        blocker_markers = (
            "rejected:",
            "conflicts",
            "blocks",
            "not confirmed",
            "insufficient",
            "no directional setup",
            "no regime reached",
            "regime confidence below",
            "invalid_location",
            "no_contextual_trigger",
            "setup_expired",
            "setup_not_active",
            "direction_mismatch",
            "unavailable",
            "error",
            "weak momentum",
            "weak volume",
            "low-volatility",
            "high-volatility",
            "unstructured",
        )
        return any(marker in text for marker in blocker_markers)
