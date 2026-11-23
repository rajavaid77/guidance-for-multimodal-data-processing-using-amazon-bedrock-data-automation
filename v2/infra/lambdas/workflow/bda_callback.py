"""EventBridge target for BDA job state events: resumes the workflow once every document of a claim finished."""

from __future__ import annotations

import json
import os
from typing import Any

import boto3

from common import db

sfn = boto3.client("stepfunctions")

SUCCESS = "Bedrock Data Automation Job Succeeded"


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    detail = event.get("detail") or {}
    source = detail.get("input_s3_object") or {}
    if source.get("s3_bucket") != os.environ["INTAKE_BUCKET"]:
        return {"ignored": "other bucket"}
    doc = db.query_one(
        "SELECT document_id, claim_id, batch_id FROM claim_documents WHERE s3_key = :k", {"k": source.get("name", "")}
    )
    if not doc:
        return {"ignored": "unknown document"}

    succeeded = event.get("detail-type") == SUCCESS and detail.get("job_status") in (None, "SUCCESS")
    output_name = (detail.get("output_s3_location") or {}).get("name")
    db.execute(
        "UPDATE claim_documents SET bda_status = :s, bda_output_prefix = :o WHERE document_id = :d",
        {"s": "SUCCESS" if succeeded else "FAILED", "o": output_name, "d": doc["document_id"]},
    )

    claim_id = doc["claim_id"]
    batch_id = doc.get("batch_id")
    # Initial documents and each additional-document batch resume their own workflow independently.
    scope = "AND batch_id = :b" if batch_id else "AND batch_id IS NULL"
    scope_params = {"c": claim_id} | ({"b": batch_id} if batch_id else {})
    pending = db.query_one(
        f"SELECT count(*) AS n FROM claim_documents WHERE claim_id = :c AND bda_status = 'RUNNING' {scope}",
        scope_params,
    )
    if pending and int(pending["n"]) > 0:
        return {"claim_id": claim_id, "waiting": int(pending["n"])}

    # Exactly one callback wins the token, even if several BDA events arrive at once.
    # RETURNING yields post-update values, so read the old token through a locked sub-select.
    if batch_id:
        token_row = db.query_one(
            """UPDATE document_batches d SET task_token = NULL, updated_at = now()
               FROM (SELECT batch_id, task_token AS old_token FROM document_batches
                     WHERE batch_id = :b AND task_token IS NOT NULL FOR UPDATE) o
               WHERE d.batch_id = o.batch_id RETURNING o.old_token AS task_token""",
            {"b": batch_id},
        )
        if token_row:
            token_row = {"bda_task_token": token_row["task_token"]}
    else:
        token_row = db.query_one(
            """UPDATE claims c SET bda_task_token = NULL, updated_at = now()
               FROM (SELECT claim_id, bda_task_token AS old_token FROM claims
                     WHERE claim_id = :c AND bda_task_token IS NOT NULL FOR UPDATE) o
               WHERE c.claim_id = o.claim_id RETURNING o.old_token AS bda_task_token""",
            {"c": claim_id},
        )
    if not token_row:
        return {"claim_id": claim_id, "already_resumed": True}
    failed = db.query_one(
        f"SELECT count(*) AS n FROM claim_documents WHERE claim_id = :c AND bda_status = 'FAILED' {scope}",
        scope_params,
    )
    token = token_row["bda_task_token"]
    try:
        if failed and int(failed["n"]) > 0:
            sfn.send_task_failure(
                taskToken=token, error="BdaJobFailed", cause=f"{failed['n']} document(s) failed extraction"
            )
        else:
            sfn.send_task_success(
                taskToken=token,
                output=json.dumps({"claim_id": claim_id} | ({"batch_id": batch_id} if batch_id else {})),
            )
    except Exception:
        # Put the token back so the EventBridge retry can resume the workflow.
        if batch_id:
            db.execute("UPDATE document_batches SET task_token = :t WHERE batch_id = :b", {"t": token, "b": batch_id})
        else:
            db.execute("UPDATE claims SET bda_task_token = :t WHERE claim_id = :c", {"t": token, "c": claim_id})
        raise
    return {"claim_id": claim_id, "resumed": True}
