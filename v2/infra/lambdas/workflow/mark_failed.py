"""Step Functions catch-all: mark the claim FAILED with a sanitized reason."""

from __future__ import annotations

import json
from typing import Any

from common import db


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    claim_id = event.get("claim_id")
    error = event.get("error") or {}
    cause = error.get("Cause") or ""
    try:
        cause = json.loads(cause).get("errorMessage", cause)
    except (ValueError, AttributeError):
        pass
    reason = f"{error.get('Error', 'Error')}: {str(cause)[:500]}"
    if claim_id:
        db.execute(
            """UPDATE claims SET status = 'FAILED', failure_reason = :r, bda_task_token = NULL,
                      review_task_token = NULL, updated_at = now() WHERE claim_id = :c""",
            {"r": reason, "c": claim_id},
        )
        db.audit(claim_id, "workflow", "FAILED", {"reason": reason})
    return {"claim_id": claim_id, "status": "FAILED", "reason": reason}
