"""Gateway tool: validate ICD-10, CPT/HCPCS, POS, modifier codes and NPIs against format rules and reference data."""

from __future__ import annotations

from typing import Any

from common import db

from .codes import CPT, HCPCS, ICD10, MODIFIER, POS, normalize_code, normalize_icd10, npi_is_valid

MAX_CODES = 60


def _lookup(table: str, codes: list[str], cols: str = "code, description") -> dict[str, dict[str, Any]]:
    if not codes:
        return {}
    names = {f"c{i}": c for i, c in enumerate(codes)}
    rows = db.query(f"SELECT {cols} FROM {table} WHERE code IN ({', '.join(':' + n for n in names)})", names)
    return {r["code"]: r for r in rows}


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    icd = sorted({normalize_icd10(c) for c in event.get("icd10_codes") or [] if c})[:MAX_CODES]
    procs = sorted({normalize_code(c) for c in event.get("procedure_codes") or [] if c})[:MAX_CODES]
    pos = sorted({normalize_code(c) for c in event.get("pos_codes") or [] if c})[:MAX_CODES]
    mods = sorted({normalize_code(c) for c in event.get("modifiers") or [] if c})[:MAX_CODES]
    npis = sorted({str(n).strip() for n in event.get("npis") or [] if n})[:MAX_CODES]

    icd_ref = _lookup("ref_icd10", [c for c in icd if ICD10.match(c)])
    proc_ref = _lookup(
        "ref_procedure", [c for c in procs if CPT.match(c) or HCPCS.match(c)], "code, description, max_units_per_day"
    )
    pos_ref = _lookup("ref_pos", [c for c in pos if POS.match(c)])
    mod_ref = _lookup("ref_modifier", [c for c in mods if MODIFIER.match(c)])
    providers = {}
    valid_npis = [n for n in npis if npi_is_valid(n)]
    if valid_npis:
        names = {f"n{i}": n for i, n in enumerate(valid_npis)}
        rows = db.query(
            f"SELECT provider_id, npi, name, in_network FROM providers WHERE npi IN ({', '.join(':' + k for k in names)})",
            names,
        )
        providers = {r["npi"]: r for r in rows}

    def result(code, ok_format, ref):
        row = ref.get(code)
        return {"code": code, "valid_format": ok_format, "in_reference_set": row is not None, **(row or {})}

    return {
        "icd10": [result(c, bool(ICD10.match(c)), icd_ref) for c in icd],
        "procedures": [
            result(c, bool(CPT.match(c) or HCPCS.match(c)), proc_ref)
            | {"code_system": "HCPCS" if HCPCS.match(c) else "CPT"}
            for c in procs
        ],
        "place_of_service": [result(c, bool(POS.match(c)), pos_ref) for c in pos],
        "modifiers": [result(c, bool(MODIFIER.match(c)), mod_ref) for c in mods],
        "npis": [{"npi": n, "check_digit_valid": npi_is_valid(n), "provider": providers.get(n)} for n in npis],
        "note": "Reference sets are a demo subset; a well-formed code missing from them is a warning, not an error.",
    }
