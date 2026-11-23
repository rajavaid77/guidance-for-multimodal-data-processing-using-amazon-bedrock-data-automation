"""Step Functions task: add the documents of one batch to the claim as evidence and decide what happens next.

The claim form and service lines of the main case are never replaced here. A CMS-1500 inside a batch is stored as
a part and as evidence only.
"""

from __future__ import annotations

import json
import os
from typing import Any

import boto3

from common import db

from .assemble_case import _segments_for

s3 = boto3.client("s3")

REVIEW_IN_PLACE, REOPEN, RECORD_ONLY = "REVIEW_IN_PLACE", "REOPEN", "RECORD_ONLY"
FINALIZED = ("APPROVED", "DENIED", "FAILED")


def _evidence(segment: dict[str, Any]) -> dict[str, Any]:
    return {
        "document_class": segment["document_class"],
        "source_key": segment["source_key"],
        "page_indices": segment["page_indices"],
        "fields": segment["fields"]
        | {k: {"value": v, "confidence": None} for k, v in segment["inference"].items() if isinstance(v, (list, dict))},
    }


def _decide(claim_id: str, batch_id: str) -> str:
    """Pick the action from the claim row. Reopening is one atomic UPDATE so concurrent batches reopen exactly once."""
    reopened = db.execute(
        """UPDATE claims SET status = 'AGENT_REVIEW', final_decision = NULL, updated_at = now()
           WHERE claim_id = :c AND status = 'PENDED_INFO_REQUESTED'""",
        {"c": claim_id},
    )
    if reopened == 1:
        db.execute("UPDATE document_batches SET reopened = TRUE WHERE batch_id = :b", {"b": batch_id})
        db.audit(claim_id, "workflow", "CLAIM_REOPENED", {"batch_id": batch_id})
        return REOPEN
    row = db.query_one("SELECT status FROM claims WHERE claim_id = :c", {"c": claim_id})
    status = (row or {}).get("status")
    if status == "PENDING_REVIEW":
        return REVIEW_IN_PLACE
    if status in FINALIZED:
        db.audit(claim_id, "workflow", "DOCUMENTS_ADDED_AFTER_DECISION", {"batch_id": batch_id, "status": status})
        return RECORD_ONLY
    raise RuntimeError(f"Claim {claim_id} is not ready for additional documents")


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    claim_id, batch_id = event["claim_id"], event["batch_id"]
    output_bucket = os.environ["BDA_OUTPUT_BUCKET"]
    intake_bucket = os.environ["INTAKE_BUCKET"]
    docs = db.query(
        """SELECT document_id, claim_id, s3_key, file_name, content_type, declared_type, bda_output_prefix, batch_id
           FROM claim_documents WHERE claim_id = :c AND batch_id = :b ORDER BY document_id""",
        {"c": claim_id, "b": batch_id},
    )
    segments = [s for d in docs for s in _segments_for(d, output_bucket, intake_bucket)]

    db.execute(
        "DELETE FROM extractions WHERE document_id IN (SELECT document_id FROM claim_documents WHERE batch_id = :b)",
        {"b": batch_id},
    )
    db.execute_many(
        """INSERT INTO extractions (claim_id, document_id, document_class, source_key, page_indices, field_name,
                                    field_value, confidence)
           VALUES (:c, :d, :cls, :k, :p, :f, :v, :conf)""",
        [
            {
                "c": claim_id,
                "d": s["doc"]["document_id"],
                "cls": s["document_class"],
                "k": s["source_key"],
                "p": ",".join(map(str, s["page_indices"])),
                "f": name,
                "v": None if f["value"] is None else str(f["value"])[:4000],
                "conf": f["confidence"],
            }
            for s in segments
            for name, f in s["fields"].items()
        ],
    )

    case_key = f"claims/{claim_id}/case.json"
    case = json.loads(s3.get_object(Bucket=output_bucket, Key=case_key)["Body"].read())
    batch_keys = {d["s3_key"] for d in docs}
    # Drop evidence from an earlier attempt of this batch so a retry does not duplicate it.
    case["evidence"] = [e for e in case.get("evidence", []) if e.get("source_key") not in batch_keys]
    case["evidence"] += [_evidence(s) for s in segments]
    s3.put_object(Bucket=output_bucket, Key=case_key, Body=json.dumps(case, default=str).encode())

    action = _decide(claim_id, batch_id)
    if action != RECORD_ONLY:
        db.execute(
            "UPDATE document_batches SET stage = 'AGENT_REVIEW', updated_at = now() WHERE batch_id = :b",
            {"b": batch_id},
        )
    db.audit(claim_id, "workflow", "BATCH_MERGED", {"batch_id": batch_id, "segments": len(segments), "action": action})
    return {"claim_id": claim_id, "case_key": case_key, "action": action}
