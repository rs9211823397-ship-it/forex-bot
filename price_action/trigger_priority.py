"""Canonical contextual-trigger names and deterministic selection priority."""


TRIGGER_PRIORITY = (
    "LIQUIDITY_REJECTION",
    "MORNING_STAR",
    "EVENING_STAR",
    "INSIDE_BAR_BREAKOUT",
    "ENGULFING",
    "REJECTION",
    "DISPLACEMENT"
)


def choose_trigger(candidates):
    candidate_set = set(candidates)

    unknown = candidate_set.difference(TRIGGER_PRIORITY)

    if unknown:
        raise ValueError(
            "Unknown trigger candidates: "
            + ", ".join(sorted(unknown))
        )

    for trigger in TRIGGER_PRIORITY:
        if trigger in candidate_set:
            return trigger

    return "NONE"
