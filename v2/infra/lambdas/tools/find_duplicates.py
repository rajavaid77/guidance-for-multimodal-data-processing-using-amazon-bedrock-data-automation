"""Gateway tool: find service lines already billed on other claims for the same member, date and procedure."""

from __future__ import annotations

from typing import Any

from common import db

from .codes import normalize_code, parse_date


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    claim_id = str(event.get("claim_id") or "")
    insured_id = str(event.get("insured_id_number") or "")
    matches = []
    for line in (event.get("service_lines") or [])[:50]:
        d = parse_date(line.get("service_date"))
        code = normalize_code(line.get("procedure_code"))
        if not (d and code and insured_id):
            continue
        rows = db.query(
            """SELECT c.claim_id, c.status, c.provider_id, c.final_decision, sl.line_number, sl.modifiers,
                      sl.units, sl.charge_amount
               FROM service_lines sl JOIN claims c ON c.claim_id = sl.claim_id
               WHERE c.insured_id_number = :iid AND c.claim_id <> :cid
                 AND c.status NOT IN ('DRAFT', 'FAILED', 'WITHDRAWN')
                 AND sl.procedure_code = :code AND sl.service_start_date = :d""",
            {"iid": insured_id, "cid": claim_id, "code": code, "d": d},
        )
        if rows:
            for r in rows:
                r["processed"] = r["status"] in ("APPROVED", "DENIED", "PENDED_INFO_REQUESTED")
            matches.append({"service_date": d.isoformat(), "procedure_code": code, "existing": rows})
    return {
        "duplicates_found": bool(matches),
        "matches": matches,
        "note": "Exact duplicate = same provider, procedure, modifiers and units on a line already processed "
        "(processed=true). Matches on claims still in review are possible duplicates (AP-130).",
    }
