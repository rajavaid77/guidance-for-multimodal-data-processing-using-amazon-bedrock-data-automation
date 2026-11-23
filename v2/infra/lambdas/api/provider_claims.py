"""Provider Portal API: create claim drafts, upload documents via pre-signed URLs, submit, track status.

Routes (all behind the Cognito authorizer; caller must be in the `providers` group with custom:provider_id):
  POST /claims                 create draft + pre-signed PUT URLs
  POST /claims/{claimId}/submit verify uploads and start processing
  GET  /claims                 list own claims
  GET  /claims/{claimId}       own claim detail
"""

from __future__ import annotations

import json
import os
import re
import uuid
from typing import Any

import boto3
from botocore.config import Config

from common import db
from common.auth import PROVIDERS, Forbidden, caller_from_event
from common.http import body_json, response

s3 = boto3.client("s3", config=Config(signature_version="s3v4", s3={"addressing_style": "virtual"}))

CONTENT_TYPES = {"application/pdf", "image/png", "image/jpeg", "image/tiff"}
DOC_TYPES = {"CMS1500", "MEDICAL_RECORD", "LAB_REPORT", "PRIMARY_EOB", "OTHER"}
MAX_DOCS = 10
MAX_BYTES = 20 * 1024 * 1024
URL_TTL = 300
CLAIM_ID = re.compile(r"^CLM-[0-9a-f]{32}$")


def _safe_name(name: str) -> str:
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", os.path.basename(name or "document"))[:100]
    return base or "document"


def _own_claim(claim_id: str, provider_id: str) -> dict[str, Any]:
    if not CLAIM_ID.match(claim_id or ""):
        raise LookupError("claim not found")
    claim = db.query_one(
        "SELECT * FROM claims WHERE claim_id = :c AND provider_id = :p", {"c": claim_id, "p": provider_id}
    )
    if not claim:
        raise LookupError("claim not found")  # same answer for "missing" and "not yours"
    return claim


def create_claim(caller, event):
    body = body_json(event)
    docs = body.get("documents") or []
    if not isinstance(docs, list) or not 1 <= len(docs) <= MAX_DOCS:
        return response(400, {"message": f"Provide 1-{MAX_DOCS} documents"})
    for d in docs:
        if d.get("content_type") not in CONTENT_TYPES:
            return response(400, {"message": f"Unsupported content type {d.get('content_type')}"})
        if d.get("declared_type") not in DOC_TYPES:
            return response(400, {"message": f"Unknown document type {d.get('declared_type')}"})
    if sum(d["declared_type"] == "CMS1500" for d in docs) != 1:
        return response(400, {"message": "Exactly one CMS-1500 claim form is required"})

    claim_id = f"CLM-{uuid.uuid4().hex}"
    db.execute(
        "INSERT INTO claims (claim_id, provider_id, submitted_by, status) VALUES (:c, :p, :u, 'DRAFT')",
        {"c": claim_id, "p": caller.provider_id, "u": caller.username},
    )
    uploads = []
    for i, d in enumerate(docs, start=1):
        key = f"claims/{claim_id}/docs/{i:02d}-{_safe_name(d.get('file_name'))}"
        db.execute(
            """INSERT INTO claim_documents (claim_id, s3_key, file_name, content_type, declared_type)
               VALUES (:c, :k, :f, :ct, :t)""",
            {
                "c": claim_id,
                "k": key,
                "f": _safe_name(d.get("file_name")),
                "ct": d["content_type"],
                "t": d["declared_type"],
            },
        )
        url = s3.generate_presigned_url(
            "put_object",
            Params={"Bucket": os.environ["INTAKE_BUCKET"], "Key": key, "ContentType": d["content_type"]},
            ExpiresIn=URL_TTL,
        )
        uploads.append({"key": key, "upload_url": url, "content_type": d["content_type"]})
    db.audit(claim_id, caller.username, "DRAFT_CREATED", {"documents": len(docs)})
    return response(201, {"claim_id": claim_id, "uploads": uploads, "expires_in": URL_TTL})


def submit_claim(caller, claim_id):
    claim = _own_claim(claim_id, caller.provider_id)
    if claim["status"] != "DRAFT":
        return response(409, {"message": f"Claim is already {claim['status']}"})
    docs = db.query("SELECT s3_key, content_type FROM claim_documents WHERE claim_id = :c", {"c": claim_id})
    bucket = os.environ["INTAKE_BUCKET"]
    for d in docs:
        try:
            head = s3.head_object(Bucket=bucket, Key=d["s3_key"])
        except s3.exceptions.ClientError:
            return response(400, {"message": f"Upload missing for {d['s3_key'].rsplit('/', 1)[-1]}"})
        if head["ContentLength"] > MAX_BYTES or head.get("ContentType") != d["content_type"]:
            return response(400, {"message": f"Invalid upload {d['s3_key'].rsplit('/', 1)[-1]}"})
    updated = db.execute(
        "UPDATE claims SET status = 'SUBMITTED', updated_at = now() WHERE claim_id = :c AND status = 'DRAFT'",
        {"c": claim_id},
    )
    if updated != 1:
        return response(409, {"message": "Claim was already submitted"})
    s3.put_object(
        Bucket=bucket,
        Key=f"claims/{claim_id}/submit.json",
        Body=json.dumps({"claim_id": claim_id, "documents": len(docs)}).encode(),
        ContentType="application/json",
    )
    db.audit(claim_id, caller.username, "SUBMITTED", {})
    return response(202, {"claim_id": claim_id, "status": "SUBMITTED"})


def list_claims(caller):
    rows = db.query(
        """SELECT claim_id, status, patient_name, total_charges, final_decision, created_at, updated_at
           FROM claims WHERE provider_id = :p ORDER BY created_at DESC LIMIT 200""",
        {"p": caller.provider_id},
    )
    return response(200, {"claims": rows})


def get_claim(caller, claim_id):
    claim = _own_claim(claim_id, caller.provider_id)
    docs = db.query(
        "SELECT file_name, declared_type, detected_type, uploaded_at FROM claim_documents WHERE claim_id = :c",
        {"c": claim_id},
    )
    lines = db.query(
        """SELECT line_number, service_start_date, procedure_code, charge_amount FROM service_lines
           WHERE claim_id = :c ORDER BY line_number""",
        {"c": claim_id},
    )
    final = db.query_one(
        """SELECT decision, line_decisions, reason, created_at FROM decisions
           WHERE claim_id = :c AND decided_by IN ('EXAMINER', 'AUTO') ORDER BY created_at DESC LIMIT 1""",
        {"c": claim_id},
    )
    public = {
        k: claim[k]
        for k in ("claim_id", "status", "patient_name", "total_charges", "final_decision", "created_at", "updated_at")
    }
    if claim["status"] == "FAILED":
        public["failure_reason"] = "Processing failed. Please contact support or resubmit."
    return response(200, {"claim": public, "documents": docs, "service_lines": lines, "decision": final})


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    try:
        caller = caller_from_event(event)
        caller.require(PROVIDERS)
        if not caller.provider_id:
            raise Forbidden("User has no provider_id attribute")
        method, resource = event.get("httpMethod"), event.get("resource")
        claim_id = (event.get("pathParameters") or {}).get("claimId", "")
        if method == "POST" and resource == "/claims":
            return create_claim(caller, event)
        if method == "POST" and resource == "/claims/{claimId}/submit":
            return submit_claim(caller, claim_id)
        if method == "GET" and resource == "/claims":
            return list_claims(caller)
        if method == "GET" and resource == "/claims/{claimId}":
            return get_claim(caller, claim_id)
        return response(404, {"message": "Not found"})
    except Forbidden:
        return response(403, {"message": "Forbidden"})
    except LookupError:
        return response(404, {"message": "Claim not found"})
    except ValueError as exc:
        return response(400, {"message": str(exc)})
