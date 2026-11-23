"""Provider Portal API: create claim drafts, upload documents via pre-signed URLs, submit, track status.

Routes (all behind the Cognito authorizer; caller must be in the `providers` group with custom:provider_id):
  POST /claims                 create draft + pre-signed PUT URLs
  POST /claims/{claimId}/submit verify uploads and start processing
  GET  /claims                 list own claims
  GET  /claims/{claimId}       own claim detail
  GET  /claims/{claimId}/parts/{partId}/url   5-minute view link for one document
  POST /claims/{claimId}/batches              add documents to a claim in progress (pre-signed PUT URLs)
  POST /claims/{claimId}/batches/{batchId}/submit  verify uploads and start the batch
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
DOC_TYPES = {"CMS1500", "MEDICAL_RECORD", "LAB_REPORT", "PRIMARY_EOB", "OTHER", "AUTO"}
BATCH_STATUSES = {"EXTRACTING", "AGENT_REVIEW", "PENDING_REVIEW", "PENDED_INFO_REQUESTED"}
MAX_DOCS = 10
MAX_CLAIM_DOCS = 30
MAX_BYTES = 20 * 1024 * 1024
URL_TTL = 300
CLAIM_ID = re.compile(r"^CLM-[0-9a-f]{32}$")
BATCH_ID = re.compile(r"^BATCH-[0-9a-f]{32}$")
PART_ID = re.compile(r"^[0-9]{1,10}$")


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
    forms = sum(d["declared_type"] == "CMS1500" for d in docs)
    if forms > 1 or (forms == 0 and not any(d["declared_type"] == "AUTO" for d in docs)):
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


def _doc_status(bda_status: str | None) -> str:
    if bda_status == "FAILED":
        return "FAILED"
    return "READY" if bda_status == "SUCCESS" else "PROCESSING"


def _documents(claim_id: str) -> list[dict[str, Any]]:
    """Part rows (one per document found by BDA); files with no parts yet fall back to a source-file row."""
    parts = db.query(
        """SELECT p.part_id, p.document_id, p.segment_index, p.display_name, p.document_class, d.declared_type,
                  p.page_start, p.page_end, d.file_name AS source_file_name, d.origin, d.bda_status,
                  p.created_at AS added_at
           FROM claim_document_parts p JOIN claim_documents d ON d.document_id = p.document_id
           WHERE p.claim_id = :c ORDER BY p.document_id, p.segment_index""",
        {"c": claim_id},
    )
    files = db.query(
        """SELECT d.document_id, d.file_name, d.declared_type, d.detected_type, d.origin, d.bda_status,
                  d.uploaded_at, d.batch_id, b.stage AS batch_stage
           FROM claim_documents d LEFT JOIN document_batches b ON b.batch_id = d.batch_id
           WHERE d.claim_id = :c ORDER BY d.document_id""",
        {"c": claim_id},
    )
    with_parts = {p["document_id"] for p in parts}
    out = [
        {
            "part_id": p["part_id"],
            "document_id": p["document_id"],
            "kind": "PACK" if p["segment_index"] < 0 else "PART",
            "name": p["display_name"],
            "document_class": p["document_class"],
            "declared_type": p["declared_type"],
            "page_start": p["page_start"],
            "page_end": p["page_end"],
            "source_file_name": p["source_file_name"],
            "origin": p["origin"],
            "status": "FAILED" if p["bda_status"] == "FAILED" else "READY",
            "added_at": p["added_at"],
        }
        for p in parts
    ]
    for f in files:
        if f["document_id"] in with_parts:
            continue
        # Documents of a batch that is still being uploaded are not part of the claim yet.
        if f["batch_id"] and f["batch_stage"] == "UPLOADING":
            continue
        out.append(
            {
                "part_id": None,
                "document_id": f["document_id"],
                "kind": "FILE",
                "name": f["file_name"],
                "document_class": f["detected_type"],
                "declared_type": f["declared_type"],
                "page_start": None,
                "page_end": None,
                "source_file_name": f["file_name"],
                "origin": f["origin"],
                "status": _doc_status(f["bda_status"]),
                "added_at": f["uploaded_at"],
            }
        )
    return out


def _view_page(part: dict[str, Any]) -> int | None:
    return part["page_start"] if part["is_original"] and (part["page_start"] or 1) > 1 else None


def get_part_url(caller, claim_id, part_id):
    _own_claim(claim_id, caller.provider_id)
    if not PART_ID.match(part_id or ""):
        raise LookupError("part not found")
    part = db.query_one(
        """SELECT s3_bucket_kind, s3_key, content_type, is_original, page_start
           FROM claim_document_parts WHERE part_id = :p AND claim_id = :c""",
        {"p": int(part_id), "c": claim_id},
    )
    if not part:
        raise LookupError("part not found")
    bucket = os.environ["BDA_OUTPUT_BUCKET" if part["s3_bucket_kind"] == "OUTPUT" else "INTAKE_BUCKET"]
    content_type = part["content_type"] or "application/pdf"
    url = s3.generate_presigned_url(
        "get_object",
        Params={
            "Bucket": bucket,
            "Key": part["s3_key"],
            "ResponseContentType": content_type,
            "ResponseContentDisposition": "inline",
        },
        ExpiresIn=URL_TTL,
    )
    return response(
        200, {"url": url, "content_type": content_type, "expires_in": URL_TTL, "page": _view_page(part)}
    )


def create_batch(caller, claim_id, event):
    claim = _own_claim(claim_id, caller.provider_id)
    if claim["status"] not in BATCH_STATUSES:
        return response(409, {"message": f"Documents cannot be added while the claim is {claim['status']}"})
    body = body_json(event)
    docs = body.get("documents") or []
    if not isinstance(docs, list) or not 1 <= len(docs) <= MAX_DOCS:
        return response(400, {"message": f"Provide 1-{MAX_DOCS} documents"})
    for d in docs:
        if d.get("content_type") not in CONTENT_TYPES:
            return response(400, {"message": f"Unsupported content type {d.get('content_type')}"})
    total = db.query_one("SELECT count(*) AS n FROM claim_documents WHERE claim_id = :c", {"c": claim_id})
    if int(total["n"]) + len(docs) > MAX_CLAIM_DOCS:
        return response(400, {"message": f"A claim can have at most {MAX_CLAIM_DOCS} files"})

    batch_id = f"BATCH-{uuid.uuid4().hex}"
    db.execute(
        "INSERT INTO document_batches (batch_id, claim_id, requested_by, stage) VALUES (:b, :c, :u, 'UPLOADING')",
        {"b": batch_id, "c": claim_id, "u": caller.username},
    )
    uploads = []
    for i, d in enumerate(docs, start=1):
        name = _safe_name(d.get("file_name"))
        key = f"claims/{claim_id}/docs/b{batch_id[6:14]}-{i:02d}-{name}"
        db.execute(
            """INSERT INTO claim_documents (claim_id, s3_key, file_name, content_type, declared_type, origin, batch_id)
               VALUES (:c, :k, :f, :ct, 'AUTO', 'ADDITIONAL', :b)""",
            {"c": claim_id, "k": key, "f": name, "ct": d["content_type"], "b": batch_id},
        )
        url = s3.generate_presigned_url(
            "put_object",
            Params={"Bucket": os.environ["INTAKE_BUCKET"], "Key": key, "ContentType": d["content_type"]},
            ExpiresIn=URL_TTL,
        )
        uploads.append({"key": key, "upload_url": url, "content_type": d["content_type"]})
    db.audit(claim_id, caller.username, "BATCH_CREATED", {"batch_id": batch_id, "documents": len(docs)})
    return response(201, {"claim_id": claim_id, "batch_id": batch_id, "uploads": uploads, "expires_in": URL_TTL})


def submit_batch(caller, claim_id, batch_id):
    claim = _own_claim(claim_id, caller.provider_id)
    if not BATCH_ID.match(batch_id or ""):
        raise LookupError("batch not found")
    batch = db.query_one(
        "SELECT stage FROM document_batches WHERE batch_id = :b AND claim_id = :c", {"b": batch_id, "c": claim_id}
    )
    if not batch:
        raise LookupError("batch not found")
    if batch["stage"] != "UPLOADING":
        return response(409, {"message": "Batch was already submitted"})
    if claim["status"] not in BATCH_STATUSES:
        return response(409, {"message": f"Documents cannot be added while the claim is {claim['status']}"})
    docs = db.query(
        "SELECT s3_key, content_type FROM claim_documents WHERE claim_id = :c AND batch_id = :b",
        {"c": claim_id, "b": batch_id},
    )
    bucket = os.environ["INTAKE_BUCKET"]
    for d in docs:
        try:
            head = s3.head_object(Bucket=bucket, Key=d["s3_key"])
        except s3.exceptions.ClientError:
            return response(400, {"message": f"Upload missing for {d['s3_key'].rsplit('/', 1)[-1]}"})
        if head["ContentLength"] > MAX_BYTES or head.get("ContentType") != d["content_type"]:
            return response(400, {"message": f"Invalid upload {d['s3_key'].rsplit('/', 1)[-1]}"})
    updated = db.execute(
        "UPDATE document_batches SET stage = 'QUEUED', updated_at = now() WHERE batch_id = :b AND stage = 'UPLOADING'",
        {"b": batch_id},
    )
    if updated != 1:
        return response(409, {"message": "Batch was already submitted"})
    s3.put_object(
        Bucket=bucket,
        Key=f"batches/{claim_id}/{batch_id}/submit.json",
        Body=json.dumps({"claim_id": claim_id, "batch_id": batch_id, "documents": len(docs)}).encode(),
        ContentType="application/json",
    )
    db.audit(claim_id, caller.username, "BATCH_SUBMITTED", {"batch_id": batch_id, "documents": len(docs)})
    return response(202, {"claim_id": claim_id, "batch_id": batch_id, "stage": "QUEUED"})


def get_claim(caller, claim_id):
    claim = _own_claim(claim_id, caller.provider_id)
    docs = _documents(claim_id)
    batches = db.query(
        """SELECT b.batch_id, b.stage, b.created_at, b.updated_at,
                  (SELECT count(*) FROM claim_documents d WHERE d.batch_id = b.batch_id) AS document_count
           FROM document_batches b WHERE b.claim_id = :c ORDER BY b.created_at DESC LIMIT 5""",
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
    return response(
        200,
        {
            "claim": public,
            "documents": docs,
            "batches": batches,
            "can_add_documents": claim["status"] in BATCH_STATUSES,
            "service_lines": lines,
            "decision": final,
        },
    )


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
        if method == "GET" and resource == "/claims/{claimId}/parts/{partId}/url":
            return get_part_url(caller, claim_id, (event.get("pathParameters") or {}).get("partId", ""))
        if method == "POST" and resource == "/claims/{claimId}/batches":
            return create_batch(caller, claim_id, event)
        if method == "POST" and resource == "/claims/{claimId}/batches/{batchId}/submit":
            return submit_batch(caller, claim_id, (event.get("pathParameters") or {}).get("batchId", ""))
        return response(404, {"message": "Not found"})
    except Forbidden:
        return response(403, {"message": "Forbidden"})
    except LookupError:
        return response(404, {"message": "Claim not found"})
    except ValueError as exc:
        return response(400, {"message": str(exc)})
