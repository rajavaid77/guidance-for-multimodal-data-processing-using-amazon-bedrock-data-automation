"""Gateway tool: member lookup, patient match, coverage on dates of service and other coverage (COB)."""

from __future__ import annotations

from typing import Any

from common import db

from .codes import name_tokens, parse_date


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    insured_id = str(event.get("insured_id_number") or "").strip()
    if not insured_id:
        return {"member_found": False, "reason": "insured_id_number is required"}

    member = db.query_one(
        """SELECT m.member_id, m.insured_name, m.birth_date, m.group_number, m.coverage_start, m.coverage_end,
                  p.plan_name, p.deductible, p.coinsurance_pct, p.eoc_document_key
           FROM members m JOIN plans p ON p.plan_id = m.plan_id WHERE m.insured_id_number = :id""",
        {"id": insured_id},
    )
    if not member:
        return {"member_found": False, "insured_id_number": insured_id}

    patients = db.query(
        "SELECT first_name, last_name, birth_date, relationship_to_insured FROM patients WHERE member_id = :m",
        {"m": member["member_id"]},
    )
    wanted_name = name_tokens(event.get("patient_name"))
    wanted_dob = parse_date(event.get("patient_date_of_birth"))
    matched = None
    for p in patients:
        tokens = name_tokens(f"{p['first_name']} {p['last_name']}")
        dob = parse_date(p.get("birth_date"))
        if len(tokens & wanted_name) >= 2:  # first and last name both present
            matched = {**p, "dob_matches": wanted_dob is None or dob == wanted_dob}
            break

    start, end = parse_date(member["coverage_start"]), parse_date(member.get("coverage_end"))
    dates = []
    for raw in event.get("service_dates") or []:
        d = parse_date(raw)
        dates.append(
            {
                "service_date": raw,
                "parsed": d.isoformat() if d else None,
                "coverage_active": bool(d and start and d >= start and (end is None or d <= end)),
            }
        )

    other = db.query(
        "SELECT payer_name, policy_number, is_primary FROM other_coverage WHERE member_id = :m",
        {"m": member["member_id"]},
    )
    return {
        "member_found": True,
        "insured_name": member["insured_name"],
        "group_number": member["group_number"],
        "plan_name": member["plan_name"],
        "plan_deductible": member["deductible"],
        "plan_coinsurance_pct": member["coinsurance_pct"],
        "coverage_start": member["coverage_start"],
        "coverage_end": member.get("coverage_end"),
        "patient_match": matched,
        "dependents_on_file": [
            f"{p['first_name']} {p['last_name']} ({p['relationship_to_insured']})" for p in patients
        ],
        "service_dates": dates,
        "other_coverage": other,
    }
