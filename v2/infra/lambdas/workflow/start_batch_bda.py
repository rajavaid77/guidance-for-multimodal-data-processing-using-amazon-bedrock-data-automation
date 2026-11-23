"""Step Functions task (.waitForTaskToken): start BDA for the documents of one additional-document batch."""

from __future__ import annotations

import re
from typing import Any

from common import db

from .start_bda import start_jobs

BATCH_ID = re.compile(r"^BATCH-[0-9a-f]{32}$")


def parse_key(key: str) -> tuple[str, str]:
    """batches/{claim_id}/{batch_id}/submit.json -> (claim_id, batch_id)."""
    parts = key.split("/")
    if len(parts) != 4 or parts[0] != "batches" or parts[3] != "submit.json" or not BATCH_ID.match(parts[2]):
        raise ValueError("Unexpected batch trigger key")
    return parts[1], parts[2]


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    claim_id, batch_id = parse_key(event["key"])
    # The UPDATE also proves the batch belongs to the claim in the key and was submitted exactly once.
    updated = db.execute(
        """UPDATE document_batches SET stage = 'EXTRACTING', task_token = :t, execution_arn = :x, updated_at = now()
           WHERE batch_id = :b AND claim_id = :c AND stage = 'QUEUED'""",
        {"t": event["task_token"], "x": event.get("execution_arn"), "b": batch_id, "c": claim_id},
    )
    if updated != 1:
        raise RuntimeError(f"Batch {batch_id} is not queued for claim {claim_id}")

    documents = db.query(
        """SELECT document_id, s3_key FROM claim_documents
           WHERE claim_id = :c AND batch_id = :b AND bda_status IS NULL ORDER BY document_id""",
        {"c": claim_id, "b": batch_id},
    )
    if not documents:
        raise RuntimeError(f"Batch {batch_id} has no documents")

    start_jobs(claim_id, documents)
    db.audit(claim_id, "workflow", "BATCH_EXTRACTION_STARTED", {"batch_id": batch_id, "documents": len(documents)})
    return {"claim_id": claim_id, "batch_id": batch_id, "documents": len(documents)}
