from ai.decision_analyzer import AIDecisionAnalyzer


def test_analyzer_marks_rejections_and_formats_report():
    analyzer = AIDecisionAnalyzer()

    report = analyzer.analyze(
        signal="HOLD",
        confidence=24,
        score=-8,
        reasons=[
            "Weak momentum",
            "Trade Quality: 40/100",
            "SELL conflicts with TREND_UP regime",
        ],
        decision_summary={
            "positive": ["Bullish EMA alignment"],
            "warnings": ["Weak momentum", "SELL conflicts with TREND_UP regime"],
        },
    )

    assert report["decision"] == "HOLD"
    assert report["approved"] is False
    assert "Trade Quality: 40/100" in report["rejection_reasons"]
    assert "SELL conflicts with TREND_UP regime" in report["rejection_reasons"]
    assert "Weak momentum" in report["rejection_reasons"]

    rendered = analyzer.format_report(report)
    assert "Decision: HOLD" in rendered
    assert "Status: REJECTED" in rendered
    assert "Rejection reasons" in rendered


def test_analyzer_keeps_approved_signal_clean():
    analyzer = AIDecisionAnalyzer()

    report = analyzer.analyze(
        signal="BUY",
        confidence=78,
        score=72,
        reasons=["Bullish EMA alignment", "Momentum confirmed"],
        decision_summary={"positive": ["Bullish EMA alignment"], "warnings": []},
    )

    assert report["decision"] == "BUY"
    assert report["approved"] is True
    assert report["rejection_reasons"] == []
