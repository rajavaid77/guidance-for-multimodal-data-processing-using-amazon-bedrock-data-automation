"""Step Functions task: let a batch merge only when the main flow and other batches are not touching the claim."""

from __future__ import annotations

from typing import Any

from common import db


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    claim_id, batch_id = event["claim_id"], event["batch_id"]
    # One atomic statement: the batch moves to MERGING only when nothing else is active on the claim.
    moved = db.execute(
        """UPDATE document_batches SET stage = 'MERGING', updated_at = now()
           WHERE batch_id = :b AND claim_id = :c AND stage IN ('EXTRACTING', 'WAITING')
             AND NOT EXISTS (SELECT 1 FROM claims WHERE claim_id = :c
                             AND status IN ('SUBMITTED', 'EXTRACTING', 'AGENT_REVIEW', 'FINALIZING'))
             AND NOT EXISTS (SELECT 1 FROM document_batches o WHERE o.claim_id = :c AND o.batch_id <> :b
                             AND o.stage IN ('MERGING', 'AGENT_REVIEW'))""",
        {"b": batch_id, "c": claim_id},
    )
    if moved == 1:
        return {"ready": True}
    current = db.query_one(
        "SELECT stage FROM document_batches WHERE batch_id = :b AND claim_id = :c", {"b": batch_id, "c": claim_id}
    )
    if current and current["stage"] == "MERGING":
        return {"ready": True}  # a retried invocation after the move already happened
    db.execute(
        """UPDATE document_batches SET stage = 'WAITING', updated_at = now()
           WHERE batch_id = :b AND claim_id = :c AND stage = 'EXTRACTING'""",
        {"b": batch_id, "c": claim_id},
    )
    return {"ready": False}
