"""Examiner UI API: review queue, review detail with evidence, and the human decision that resumes the workflow.

Routes (Cognito authorizer; caller must be in the `examiners` group):
  GET  /reviews                      queue (default PENDING_REVIEW)
  GET  /reviews/{claimId}            full review package
  POST /reviews/{claimId}/decision   {decision, reason, line_decisions?}
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

import boto3
from botocore.config import Config

from common import db
from common.auth import EXAMINERS, Forbidden, caller_from_event
from common.http import body_json, response

s3 = boto3.client("s3", config=Config(signature_version="s3v4", s3={"addressing_style": "virtual"}))
sfn = boto3.client("stepfunctions")

CLAIM_ID = re.compile(r"^CLM-[0-9a-f]{32}$")
DECISIONS = {"APPROVE", "DENY", "PEND"}
STATUSES = {"PENDING_REVIEW", "APPROVED", "DENIED", "PENDED_INFO_REQUESTED", "FAILED", "AGENT_REVIEW", "EXTRACTING"}


def list_reviews(event):
    status = ((event.get("queryStringParameters") or {}).get("status") or "PENDING_REVIEW").upper()
    if status not in STATUSES:
        return response(400, {"message": "Unknown status"})
    rows = db.query(
        """SELECT c.claim_id, c.status, c.patient_name, c.total_charges, c.agent_decision, c.agent_confidence,
                  p.name AS provider_name, c.created_at, c.updated_at
           FROM claims c JOIN providers p ON p.provider_id = c.provider_id
           WHERE c.status = :s ORDER BY c.updated_at ASC LIMIT 200""",
        {"s": status},
    )
    return response(200, {"reviews": rows})


def get_review(claim_id):
    claim = db.query_one(
        """SELECT c.claim_id, c.status, c.patient_name, c.insured_id_number, c.total_charges, c.agent_decision,
                  c.agent_confidence, c.final_decision, c.failure_reason, c.created_at, c.updated_at,
                  p.provider_id, p.name AS provider_name, p.npi AS provider_npi
           FROM claims c JOIN providers p ON p.provider_id = c.provider_id WHERE c.claim_id = :c""",
        {"c": claim_id},
    )
    if not claim:
        raise LookupError
    docs = db.query(
        """SELECT document_id, s3_key, file_name, content_type, declared_type, detected_type
           FROM claim_documents WHERE claim_id = :c ORDER BY document_id""",
        {"c": claim_id},
    )
    for d in docs:
        d["view_url"] = s3.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": os.environ["INTAKE_BUCKET"],
                "Key": d.pop("s3_key"),
                "ResponseContentType": d["content_type"],
                "ResponseContentDisposition": "inline",
            },
            ExpiresIn=300,
        )
    extractions = db.query(
        """SELECT document_class, page_indices, field_name, field_value, confidence FROM extractions
           WHERE claim_id = :c ORDER BY document_class, field_name""",
        {"c": claim_id},
    )
    lines = db.query("SELECT * FROM service_lines WHERE claim_id = :c ORDER BY line_number", {"c": claim_id})
    run = db.query_one(
        "SELECT recommendation, created_at FROM agent_runs WHERE claim_id = :c ORDER BY created_at DESC LIMIT 1",
        {"c": claim_id},
    )
    recommendation = run and run["recommendation"]
    if isinstance(recommendation, str):
        recommendation = json.loads(recommendation)
    history = db.query(
        "SELECT decided_by, actor, decision, reason, created_at FROM decisions WHERE claim_id = :c ORDER BY created_at",
        {"c": claim_id},
    )
    return response(
        200,
        {
            "claim": claim,
            "documents": docs,
            "extractions": extractions,
            "service_lines": lines,
            "recommendation": recommendation,
            "decisions": history,
        },
    )


def decide(caller, claim_id, event):
    body = body_json(event)
    decision = str(body.get("decision") or "").upper()
    reason = str(body.get("reason") or "").strip()
    if decision not in DECISIONS:
        return response(400, {"message": "decision must be APPROVE, DENY or PEND"})
    if len(reason) < 5:
        return response(400, {"message": "A reason is required"})
    line_decisions = body.get("line_decisions") or []
    if not isinstance(line_decisions, list):
        return response(400, {"message": "line_decisions must be an array"})

    token_row = db.query_one(
        """UPDATE claims c SET review_task_token = NULL, status = 'FINALIZING', updated_at = now()
           FROM (SELECT claim_id, review_task_token AS old_token FROM claims
                 WHERE claim_id = :c AND status = 'PENDING_REVIEW' AND review_task_token IS NOT NULL FOR UPDATE) o
           WHERE c.claim_id = o.claim_id RETURNING o.old_token AS review_task_token""",
        {"c": claim_id},
    )
    if not token_row:
        return response(409, {"message": "Claim is not awaiting review"})
    try:
        _resume(token_row["review_task_token"], claim_id, decision, reason, line_decisions, caller.username)
    except sfn.exceptions.ClientError:
        db.execute(
            "UPDATE claims SET status = 'FAILED', failure_reason = 'Review task expired' WHERE claim_id = :c",
            {"c": claim_id},
        )
        return response(409, {"message": "The review task expired; the claim was marked FAILED"})
    db.audit(claim_id, caller.username, "EXAMINER_DECISION", {"decision": decision})
    return response(202, {"claim_id": claim_id, "decision": decision})


def _resume(token, claim_id, decision, reason, line_decisions, actor):
    sfn.send_task_success(
        taskToken=token,
        output=json.dumps(
            {
                "claim_id": claim_id,
                "decision": decision,
                "reason": reason[:4000],
                "line_decisions": line_decisions,
                "decided_by": "EXAMINER",
                "actor": actor,
            }
        ),
    )


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    try:
        caller = caller_from_event(event)
        caller.require(EXAMINERS)
        method, resource = event.get("httpMethod"), event.get("resource")
        claim_id = (event.get("pathParameters") or {}).get("claimId", "")
        if claim_id and not CLAIM_ID.match(claim_id):
            raise LookupError
        if method == "GET" and resource == "/reviews":
            return list_reviews(event)
        if method == "GET" and resource == "/reviews/{claimId}":
            return get_review(claim_id)
        if method == "POST" and resource == "/reviews/{claimId}/decision":
            return decide(caller, claim_id, event)
        return response(404, {"message": "Not found"})
    except Forbidden:
        return response(403, {"message": "Forbidden"})
    except LookupError:
        return response(404, {"message": "Claim not found"})
    except ValueError as exc:
        return response(400, {"message": str(exc)})
