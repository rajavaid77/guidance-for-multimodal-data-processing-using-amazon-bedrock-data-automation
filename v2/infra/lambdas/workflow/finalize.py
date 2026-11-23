"""Step Functions task: record the final decision (auto or examiner) and close the claim."""

from __future__ import annotations

from typing import Any

from common import db

STATUS = {"APPROVE": "APPROVED", "DENY": "DENIED", "PEND": "PENDED_INFO_REQUESTED"}


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    claim_id = event["claim_id"]
    decision = event["decision"]
    if decision not in STATUS:
        raise ValueError(f"Unknown decision {decision}")
    decided_by = event.get("decided_by", "AUTO")
    actor = event.get("actor", "workflow")
    db.execute(
        """INSERT INTO decisions (claim_id, decided_by, actor, decision, line_decisions, reason)
           VALUES (:c, :by, :a, :d, :l, :r)""",
        {
            "c": claim_id,
            "by": decided_by,
            "a": actor,
            "d": decision,
            "l": db.Typed(event.get("line_decisions") or [], "JSON"),
            "r": str(event.get("reason") or "")[:4000],
        },
    )
    db.execute(
        """UPDATE claims SET status = :s, final_decision = :d, review_task_token = NULL, updated_at = now()
           WHERE claim_id = :c""",
        {"s": STATUS[decision], "d": decision, "c": claim_id},
    )
    db.audit(claim_id, actor, "FINALIZED", {"decision": decision, "decided_by": decided_by})
    return {"claim_id": claim_id, "status": STATUS[decision]}
