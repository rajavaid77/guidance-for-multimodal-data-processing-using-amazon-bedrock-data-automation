"""Auto-finalize vs. human review routing (pure function, unit tested)."""

from __future__ import annotations

from typing import Any


def route(
    recommendation: dict[str, Any],
    total_charges: float | None,
    plan_limit: float | None,
    confidence_threshold: float,
    global_limit: float,
) -> tuple[str, str]:
    limit = min(x for x in (plan_limit, global_limit) if x is not None)
    if recommendation.get("decision") != "APPROVE":
        return (
            "REVIEW",
            f"Agent recommended {recommendation.get('decision')}; every non-approval is reviewed by a human",
        )
    if not recommendation.get("all_checks_passed"):
        return "REVIEW", "Not all checks passed"
    if float(recommendation.get("confidence") or 0) < confidence_threshold:
        return "REVIEW", f"Confidence below {confidence_threshold}"
    if total_charges is None or total_charges > limit:
        return "REVIEW", f"Total charges exceed auto-approve limit {limit}"
    return "AUTO", "All checks passed with high confidence under the auto-approve limit"
