"""Examiner UI API: review queue, review detail with evidence, and the human decision that resumes the workflow.

Routes (Cognito authorizer; caller must be in the `examiners` group):
  GET  /reviews                      queue (default PENDING_REVIEW)
  GET  /reviews/{claimId}            full review package
  GET  /reviews/{claimId}/parts/{partId}/url   5-minute view link for one document
  POST /reviews/{claimId}/decision   {decision, reason, line_decisions?}
  POST /reviews/{claimId}/rerun      {mode: "AGENT", reason}  re-run the agent review on the stored case
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from common import db
from common.auth import EXAMINERS, Forbidden, caller_from_event
from common.http import body_json, response

s3 = boto3.client("s3", config=Config(signature_version="s3v4", s3={"addressing_style": "virtual"}))
sfn = boto3.client("stepfunctions")

CLAIM_ID = re.compile(r"^CLM-[0-9a-f]{32}$")
PART_ID = re.compile(r"^[0-9]{1,10}$")
URL_TTL = 300
DECISIONS = {"APPROVE", "DENY", "PEND"}
MODES = {"AGENT"}
RERUN_STATUSES = ("PENDING_REVIEW", "FAILED", "PENDED_INFO_REQUESTED")
# A recorded PEND means "more information needed", not a final outcome, so it may be re-run. APPROVE and DENY may not.
RERUNNABLE_FINAL_DECISIONS = (None, "PEND")
REASON_MIN, REASON_MAX = 10, 1000
_CONTROL = re.compile(r"[\x00-\x09\x0b-\x1f\x7f]")
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


def _sign(bucket, key, content_type):
    return s3.generate_presigned_url(
        "get_object",
        Params={
            "Bucket": bucket,
            "Key": key,
            "ResponseContentType": content_type,
            "ResponseContentDisposition": "inline",
        },
        ExpiresIn=URL_TTL,
    )


def get_part_url(claim_id, part_id):
    if not PART_ID.match(part_id or ""):
        raise LookupError
    part = db.query_one(
        """SELECT s3_bucket_kind, s3_key, content_type, is_original, page_start
           FROM claim_document_parts WHERE part_id = :p AND claim_id = :c""",
        {"p": int(part_id), "c": claim_id},
    )
    if not part:
        raise LookupError
    bucket = os.environ["BDA_OUTPUT_BUCKET" if part["s3_bucket_kind"] == "OUTPUT" else "INTAKE_BUCKET"]
    content_type = part["content_type"] or "application/pdf"
    page = part["page_start"] if part["is_original"] and (part["page_start"] or 1) > 1 else None
    return response(
        200,
        {
            "url": _sign(bucket, part["s3_key"], content_type),
            "content_type": content_type,
            "expires_in": URL_TTL,
            "page": page,
        },
    )


def get_review(claim_id):
    claim = db.query_one(
        """SELECT c.claim_id, c.status, c.patient_name, c.insured_id_number, c.total_charges, c.agent_decision,
                  c.agent_confidence, c.final_decision, c.failure_reason, c.created_at, c.updated_at,
                  c.current_run, c.submitted_by, p.provider_id, p.name AS provider_name, p.npi AS provider_npi
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
    parts = db.query(
        """SELECT p.part_id, p.document_id, p.display_name AS name, p.document_class, p.page_start, p.page_end,
                  CASE WHEN p.segment_index < 0 THEN 'PACK' ELSE 'PART' END AS kind,
                  d.file_name AS source_file_name, d.declared_type, d.origin
           FROM claim_document_parts p JOIN claim_documents d ON d.document_id = p.document_id
           WHERE p.claim_id = :c ORDER BY p.document_id, p.segment_index""",
        {"c": claim_id},
    )
    for d in docs:
        key = d.pop("s3_key")
        if not parts:
            # Claims processed before parts were recorded keep the legacy per-file link.
            d["view_url"] = _sign(os.environ["INTAKE_BUCKET"], key, d["content_type"])
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
        """SELECT decided_by, actor, decision, reason, created_at, claim_run_id FROM decisions
           WHERE claim_id = :c ORDER BY created_at""",
        {"c": claim_id},
    )
    runs = _runs(claim_id, claim, history)
    in_flight = _batches_in_flight(claim_id)
    can_rerun = (
        claim["status"] in RERUN_STATUSES and claim["final_decision"] in RERUNNABLE_FINAL_DECISIONS and in_flight == 0
    )
    if can_rerun and claim["status"] == "FAILED":
        # A claim that failed during extraction never produced a case: offering the button would only end in a 409.
        can_rerun = _has_case(claim_id)
    return response(
        200,
        {
            "claim": claim,
            "documents": docs,
            "parts": parts,
            "extractions": extractions,
            "service_lines": lines,
            "recommendation": recommendation,
            "decisions": history,
            "runs": runs,
            "current_run": claim["current_run"],
            "can_rerun": can_rerun,
        },
    )


def _has_case(claim_id):
    """True when the claim reached the agent step once (a stored case.json exists), so Mode A has input to re-run."""
    try:
        s3.head_object(Bucket=os.environ["BDA_OUTPUT_BUCKET"], Key=f"claims/{claim_id}/case.json")
    except ClientError:
        return False
    return True


def _batches_in_flight(claim_id):
    row = db.query_one(
        """SELECT COUNT(*) AS n FROM document_batches WHERE claim_id = :c
           AND stage IN ('QUEUED', 'EXTRACTING', 'WAITING', 'MERGING', 'AGENT_REVIEW')""",
        {"c": claim_id},
    )
    return int((row or {}).get("n") or 0)


def _runs(claim_id, claim, history):
    """Run 1 is the original submission (synthesized); later runs come from claim_runs. Reasons are examiner-only."""
    rows = db.query(
        """SELECT run_id, mode, requested_by, requested_at, reason, status FROM claim_runs
           WHERE claim_id = :c ORDER BY run_id""",
        {"c": claim_id},
    )
    agent = {}
    for a in db.query(
        """SELECT claim_run_id, recommendation->>'decision' AS decision, recommendation->>'confidence' AS confidence
           FROM agent_runs WHERE claim_id = :c ORDER BY created_at""",
        {"c": claim_id},
    ):
        agent[int(a["claim_run_id"])] = a
    final = {}
    for d in history:
        if d["decided_by"] in ("AUTO", "EXAMINER"):
            final[int(d.get("claim_run_id") or 1)] = d["decision"]
    runs = [
        {
            "run_id": 1,
            "mode": "INITIAL",
            "requested_by": claim.get("submitted_by"),
            "requested_at": claim["created_at"],
            "reason": None,
        },
        *rows,
    ]
    current = int(claim.get("current_run") or 1)
    out = []
    for r in runs:
        n = int(r["run_id"])
        if r.get("status") in ("START_FAILED", "ABORTED"):
            outcome = r["status"]
        elif n in final:
            outcome = final[n]
        elif n == current:
            outcome = claim["status"]
        else:
            outcome = "SUPERSEDED"
        a = agent.get(n) or {}
        out.append(
            {
                "run_id": n,
                "mode": r["mode"],
                "requested_by": r["requested_by"],
                "requested_at": r["requested_at"],
                "reason": r["reason"],
                "outcome": outcome,
                "agent_decision": a.get("decision"),
                "agent_confidence": a.get("confidence"),
                "final_decision": final.get(n),
            }
        )
    return out


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


def _clean_reason(raw):
    text = _CONTROL.sub("", str(raw or "")).strip()
    if len(text) < REASON_MIN or len(text) > REASON_MAX:
        raise ValueError(f"A reason of {REASON_MIN} to {REASON_MAX} characters is required")
    return text


def _blocker(claim_id):
    """Return the 409 message explaining why a re-run is not allowed, or None when the claim is eligible."""
    row = db.query_one("SELECT status, final_decision FROM claims WHERE claim_id = :c", {"c": claim_id})
    if not row:
        raise LookupError
    if row["final_decision"] not in RERUNNABLE_FINAL_DECISIONS:
        return "This claim is finalized and cannot be re-run"
    if _batches_in_flight(claim_id):
        return "Additional documents are being processed; try again when they finish"
    if row["status"] not in RERUN_STATUSES:
        return "A review is already in progress for this claim"
    return None


def _is_gone(exc):
    return exc.response.get("Error", {}).get("Code") == "ExecutionDoesNotExist"


def _restore(claim_id, run_id, old, actor, cause):
    db.execute(
        """UPDATE claims SET status = :s, review_task_token = :t, execution_arn = :a, failure_reason = :f,
                  updated_at = now()
           WHERE claim_id = :c AND current_run = :r AND status = 'AGENT_REVIEW'""",
        {
            "s": old["old_status"],
            "t": old["old_token"],
            "a": old["old_arn"],
            "f": old["old_failure"],
            "c": claim_id,
            "r": run_id,
        },
    )
    db.execute(
        "UPDATE claim_runs SET status = 'ABORTED' WHERE claim_id = :c AND run_id = :r", {"c": claim_id, "r": run_id}
    )
    db.audit(claim_id, actor, "RERUN_ABORTED", {"run_id": run_id, "cause": cause, "restored_status": old["old_status"]})


def rerun(caller, claim_id, event):
    """Mode A: re-run the agent review on the stored case. Never touches parts or extractions; never logs the reason."""
    body = body_json(event)
    mode = str(body.get("mode") or "").upper()
    if mode == "EXTRACTION":
        return response(400, {"message": "Mode not supported yet"})
    if mode not in MODES:
        return response(400, {"message": "mode must be AGENT"})
    reason = _clean_reason(body.get("reason"))
    blocked = _blocker(claim_id)
    if blocked:
        return response(409, {"message": blocked})
    case_key = f"claims/{claim_id}/case.json"
    if not _has_case(claim_id):
        return response(409, {"message": "No stored case; this claim never finished extraction"})
    old = db.query_one(
        """UPDATE claims c SET status = 'AGENT_REVIEW', review_task_token = NULL, failure_reason = NULL,
                  final_decision = NULL, current_run = c.current_run + 1, updated_at = now()
           FROM (SELECT claim_id, status AS old_status, review_task_token AS old_token, execution_arn AS old_arn,
                        failure_reason AS old_failure
                 FROM claims
                 WHERE claim_id = :c
                   AND ((status IN ('PENDING_REVIEW', 'FAILED') AND final_decision IS NULL)
                        OR (status = 'PENDED_INFO_REQUESTED' AND final_decision = 'PEND'))
                   AND NOT EXISTS (SELECT 1 FROM document_batches b WHERE b.claim_id = :c
                                   AND b.stage IN ('QUEUED', 'EXTRACTING', 'WAITING', 'MERGING', 'AGENT_REVIEW'))
                 FOR UPDATE) o
           WHERE c.claim_id = o.claim_id
           RETURNING c.current_run AS run_id, o.old_status, o.old_token, o.old_arn, o.old_failure""",
        {"c": claim_id},
    )
    if not old:
        return response(409, {"message": _blocker(claim_id) or "The claim changed; reload and try again"})
    run_id = int(old["run_id"])
    db.execute(
        """INSERT INTO claim_runs (claim_id, run_id, mode, reason, requested_by, prior_status, prior_failure_reason,
                                   prior_execution_arn, case_key)
           VALUES (:c, :r, :m, :why, :u, :ps, :pf, :pa, :k)""",
        {
            "c": claim_id,
            "r": run_id,
            "m": mode,
            "why": reason,
            "u": caller.username,
            "ps": old["old_status"],
            "pf": old["old_failure"],
            "pa": old["old_arn"],
            "k": case_key,
        },
    )
    db.audit(
        claim_id,
        caller.username,
        "RERUN_REQUESTED",
        {"run_id": run_id, "mode": mode, "prior_status": old["old_status"]},
    )
    if old["old_status"] == "PENDING_REVIEW":
        if not old["old_arn"]:
            _restore(claim_id, run_id, old, caller.username, "NO_EXECUTION_ARN")
            return response(409, {"message": "Cannot identify the waiting review; nothing was changed"})
        try:
            sfn.stop_execution(executionArn=old["old_arn"], cause="Superseded by a re-run")
        except ClientError as exc:
            if not _is_gone(exc):
                _restore(claim_id, run_id, old, caller.username, "STOP_FAILED")
                return response(502, {"message": "Could not stop the previous review; nothing was changed"})
    try:
        started = sfn.start_execution(
            stateMachineArn=os.environ["STATE_MACHINE_ARN"],
            name=f"{claim_id}-run{run_id}",
            input=json.dumps(
                {"entry": "AGENT", "claim_id": claim_id, "run_id": run_id, "case": {"case_key": case_key}}
            ),
        )
    except ClientError:
        if old["old_status"] == "PENDED_INFO_REQUESTED":
            # Nothing ran, so the claim keeps its recorded PEND and the provider's view is unchanged.
            db.execute(
                """UPDATE claims SET status = 'PENDED_INFO_REQUESTED', final_decision = 'PEND', updated_at = now()
                   WHERE claim_id = :c AND current_run = :r AND status = 'AGENT_REVIEW'""",
                {"c": claim_id, "r": run_id},
            )
        else:
            db.execute(
                """UPDATE claims SET status = 'FAILED', failure_reason = 'Re-run could not be started',
                          updated_at = now()
                   WHERE claim_id = :c AND current_run = :r AND status = 'AGENT_REVIEW'""",
                {"c": claim_id, "r": run_id},
            )
        db.execute(
            "UPDATE claim_runs SET status = 'START_FAILED' WHERE claim_id = :c AND run_id = :r",
            {"c": claim_id, "r": run_id},
        )
        db.audit(claim_id, caller.username, "RERUN_START_FAILED", {"run_id": run_id})
        return response(502, {"message": "The re-run could not be started; the claim can be re-run again"})
    arn = started.get("executionArn")
    db.execute(
        "UPDATE claim_runs SET execution_arn = :a WHERE claim_id = :c AND run_id = :r",
        {"a": arn, "c": claim_id, "r": run_id},
    )
    db.execute(
        "UPDATE claims SET execution_arn = :a WHERE claim_id = :c AND current_run = :r",
        {"a": arn, "c": claim_id, "r": run_id},
    )
    return response(202, {"claim_id": claim_id, "run_id": run_id, "mode": mode, "status": "AGENT_REVIEW"})


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
        if method == "GET" and resource == "/reviews/{claimId}/parts/{partId}/url":
            return get_part_url(claim_id, (event.get("pathParameters") or {}).get("partId", ""))
        if method == "POST" and resource == "/reviews/{claimId}/decision":
            return decide(caller, claim_id, event)
        if method == "POST" and resource == "/reviews/{claimId}/rerun":
            return rerun(caller, claim_id, event)
        return response(404, {"message": "Not found"})
    except Forbidden:
        return response(403, {"message": "Forbidden"})
    except LookupError:
        return response(404, {"message": "Claim not found"})
    except ValueError as exc:
        return response(400, {"message": str(exc)})
