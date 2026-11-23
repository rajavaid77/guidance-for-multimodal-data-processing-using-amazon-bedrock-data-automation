"""Step Functions task: read BDA outputs, persist extractions and service lines, write the claim case to S3."""

from __future__ import annotations

import json
import os
from typing import Any
from urllib.parse import urlparse

import boto3

from common import db
from tools.codes import normalize_code, parse_date

from .bda_output import build_case, segment_record

s3 = boto3.client("s3")


def _read_json(uri_or_bucket: str, key: str | None = None) -> dict[str, Any]:
    if key is None:
        parsed = urlparse(uri_or_bucket)
        uri_or_bucket, key = parsed.netloc, parsed.path.lstrip("/")
    return json.loads(s3.get_object(Bucket=uri_or_bucket, Key=key)["Body"].read())


def _segments_for(doc: dict[str, Any], bucket: str) -> list[dict[str, Any]]:
    prefix, _, asset_id = (doc.get("bda_output_prefix") or "").rpartition("/")
    if not prefix:
        return []
    metadata = _read_json(bucket, f"{prefix}/job_metadata.json")
    segments = []
    for item in metadata.get("output_metadata") or []:
        if asset_id and str(item.get("asset_id")) != asset_id:
            continue
        for segment in item.get("segment_metadata") or []:
            if segment.get("custom_output_path") and segment.get("custom_output_status", "MATCH") == "MATCH":
                segments.append(segment_record(_read_json(segment["custom_output_path"]), doc["s3_key"]) | {"doc": doc})
    return segments


def _num(value: Any) -> float | None:
    try:
        return float(str(value).replace("$", "").replace(",", "")) if value not in (None, "") else None
    except ValueError:
        return None


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    claim_id = event["claim_id"]
    output_bucket = os.environ["BDA_OUTPUT_BUCKET"]
    claim = db.query_one(
        """SELECT c.claim_id, p.provider_id, p.npi, p.name FROM claims c JOIN providers p ON p.provider_id = c.provider_id
           WHERE c.claim_id = :id""",
        {"id": claim_id},
    )
    docs = db.query(
        "SELECT document_id, s3_key, declared_type, bda_output_prefix FROM claim_documents WHERE claim_id = :id",
        {"id": claim_id},
    )
    segments = [s for d in docs for s in _segments_for(d, output_bucket)]
    case = build_case(
        claim_id,
        {"provider_id": claim["provider_id"], "npi": claim["npi"], "name": claim["name"]},
        segments,
        float(os.environ.get("CONFIDENCE_THRESHOLD", "0.8")),
    )

    db.execute("DELETE FROM extractions WHERE claim_id = :id", {"id": claim_id})
    db.execute("DELETE FROM service_lines WHERE claim_id = :id", {"id": claim_id})
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
    db.execute_many(
        """INSERT INTO service_lines (claim_id, line_number, service_start_date, service_end_date, place_of_service,
                                      procedure_code, modifiers, diagnosis_pointer, units, charge_amount, rendering_npi)
           VALUES (:c, :n, :sd, :ed, :pos, :code, :mods, :ptr, :units, :charge, :npi)""",
        [
            {
                "c": claim_id,
                "n": line["line_number"],
                "sd": parse_date(line["service_start_date"]),
                "ed": parse_date(line["service_end_date"]),
                "pos": (line["place_of_service"] or None) and str(line["place_of_service"])[:10],
                "code": normalize_code(line["procedure_code"]) or None,
                "mods": (line["modifiers"] or None) and str(line["modifiers"])[:20],
                "ptr": (line["diagnosis_pointer"] or None) and str(line["diagnosis_pointer"])[:10],
                "units": _num(line["units"]),
                "charge": _num(line["charge_amount"]),
                "npi": (line["rendering_provider_npi"] or None) and str(line["rendering_provider_npi"])[:10],
            }
            for line in case["service_lines"]
        ],
    )
    for s in segments:
        db.execute(
            "UPDATE claim_documents SET detected_type = :t WHERE document_id = :d",
            {"t": s["document_class"], "d": s["doc"]["document_id"]},
        )

    form = case["cms1500"]
    insured_id = (form.get("insured_id_number") or {}).get("value")
    member = db.query_one("SELECT member_id FROM members WHERE insured_id_number = :i", {"i": str(insured_id or "")})
    db.execute(
        """UPDATE claims SET status = 'AGENT_REVIEW', patient_name = :pn, insured_id_number = :iid, member_id = :m,
                  total_charges = :t, updated_at = now() WHERE claim_id = :id""",
        {
            "pn": str((form.get("patient_name") or {}).get("value") or "")[:200] or None,
            "iid": str(insured_id)[:50] if insured_id else None,
            "m": member["member_id"] if member else None,
            "t": _num((form.get("total_charges") or {}).get("value")),
            "id": claim_id,
        },
    )
    case_key = f"claims/{claim_id}/case.json"
    s3.put_object(Bucket=output_bucket, Key=case_key, Body=json.dumps(case, default=str).encode())
    db.audit(
        claim_id,
        "workflow",
        "CASE_ASSEMBLED",
        {"segments": len(segments), "low_confidence": case["low_confidence_fields"]},
    )
    return {"claim_id": claim_id, "case_key": case_key}
