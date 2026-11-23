"""Step Functions catch-all for the batch workflow: fail the batch, and the claim only if this batch reopened it."""

from __future__ import annotations

import json
from typing import Any

from common import db


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    claim_id, batch_id = event.get("claim_id"), event.get("batch_id")
    error = event.get("error") or {}
    cause = error.get("Cause") or ""
    try:
        cause = json.loads(cause).get("errorMessage", cause)
    except (ValueError, AttributeError):
        pass
    reason = f"{error.get('Error', 'Error')}: {str(cause)[:500]}"
    if not (claim_id and batch_id):
        return {"claim_id": claim_id, "batch_id": batch_id, "stage": "FAILED"}
    row = db.query_one(
        """UPDATE document_batches SET stage = 'FAILED', task_token = NULL, completed_at = now(), updated_at = now()
           WHERE batch_id = :b AND claim_id = :c RETURNING reopened""",
        {"b": batch_id, "c": claim_id},
    )
    db.execute(
        """UPDATE claim_documents SET bda_status = 'FAILED'
           WHERE claim_id = :c AND batch_id = :b AND bda_status = 'RUNNING'""",
        {"c": claim_id, "b": batch_id},
    )
    claim_failed = bool(row and row.get("reopened"))
    if claim_failed:
        # The claim was moved out of PENDED_INFO_REQUESTED by this batch and would otherwise stay in AGENT_REVIEW.
        db.execute(
            """UPDATE claims SET status = 'FAILED', failure_reason = :r, bda_task_token = NULL,
                      review_task_token = NULL, updated_at = now() WHERE claim_id = :c""",
            {"r": reason, "c": claim_id},
        )
    db.audit(
        claim_id, "workflow", "BATCH_FAILED", {"batch_id": batch_id, "reason": reason, "claim_failed": claim_failed}
    )
    return {"claim_id": claim_id, "batch_id": batch_id, "stage": "FAILED", "claim_failed": claim_failed}
