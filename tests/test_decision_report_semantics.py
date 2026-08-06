from ai.decision_analyzer import AIDecisionAnalyzer


def test_hold_report_is_held_not_execution_rejected_and_filters_opposite_evidence():
    analyzer = AIDecisionAnalyzer()
    report = analyzer.analyze(
        signal="HOLD",
        confidence=70,
        score=65,
        reasons=[
            "Bullish EMA alignment",
            "Bearish momentum confirmed",
            "Contextual INVALID_LOCATION",
            "Rejected: Contextual trigger rejected setup",
        ],
        decision_summary={
            "positive": [
                "Bullish EMA alignment",
                "Bearish momentum confirmed",
                "Market structure bullish",
            ],
            "warnings": ["Rejected: Contextual trigger rejected setup"],
        },
    )

    assert report["status"] == "HELD"
    assert report["candidate_direction"] == "BUY"
    assert "Bearish momentum confirmed" not in report["decision_summary"]["positive"]
    assert report["primary_reason"] == "Rejected: Contextual trigger rejected setup"

    text = analyzer.format_report(report)
    assert "Status: HELD" in text
    assert "Candidate bias: BUY" in text
    assert "Primary blocker: Contextual trigger rejected setup" in text
    assert "Trade quality: 70/100" in text
