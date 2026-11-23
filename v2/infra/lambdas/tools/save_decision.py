"""Gateway tool: persist the adjudication agent's recommendation for a claim currently under agent review."""

from __future__ import annotations

from typing import Any

from common import db

DECISIONS = {"APPROVE", "DENY", "PEND"}


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    claim_id = str(event.get("claim_id") or "")
    decision = str(event.get("decision") or "").upper()
    if decision not in DECISIONS:
        return {"saved": False, "error": f"decision must be one of {sorted(DECISIONS)}"}
    try:
        confidence = max(0.0, min(1.0, float(event.get("confidence", 0))))
    except (TypeError, ValueError):
        return {"saved": False, "error": "confidence must be a number between 0 and 1"}
    line_decisions = event.get("line_decisions") or []
    if not isinstance(line_decisions, list):
        return {"saved": False, "error": "line_decisions must be an array"}

    # Only a claim that the workflow has handed to the agent may be written (limits prompt-injection blast radius).
    updated = db.execute(
        """UPDATE claims SET agent_decision = :d, agent_confidence = :c, updated_at = now()
           WHERE claim_id = :id AND status = 'AGENT_REVIEW'""",
        {"d": decision, "c": confidence, "id": claim_id},
    )
    if updated != 1:
        return {"saved": False, "error": "claim is not under agent review"}
    db.execute(
        """INSERT INTO decisions (claim_id, decided_by, actor, decision, line_decisions, reason, claim_run_id)
           VALUES (:id, 'AGENT', 'adjudication-agent', :d, :lines, :r,
                   (SELECT current_run FROM claims WHERE claim_id = :id))""",
        {
            "id": claim_id,
            "d": decision,
            "lines": db.Typed(line_decisions, "JSON"),
            "r": str(event.get("rationale", ""))[:4000],
        },
    )
    db.audit(claim_id, "adjudication-agent", "AGENT_DECISION_SAVED", {"decision": decision, "confidence": confidence})
    return {"saved": True, "claim_id": claim_id, "decision": decision}
