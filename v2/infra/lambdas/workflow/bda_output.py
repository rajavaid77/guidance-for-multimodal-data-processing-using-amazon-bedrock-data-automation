"""Parse Bedrock Data Automation custom output into a ClaimCase (pure functions, unit tested)."""

from __future__ import annotations

from typing import Any

CMS1500, MEDICAL_RECORD, LAB_REPORT, PRIMARY_EOB = "CMS1500", "MEDICAL_RECORD", "LAB_REPORT", "PRIMARY_EOB"
_CLASS_BY_TOKEN = {
    "cms1500": CMS1500,
    "medical-record": MEDICAL_RECORD,
    "lab-report": LAB_REPORT,
    "primary-eob": PRIMARY_EOB,
}

KEY_FIELDS = (
    "insured_id_number",
    "patient_name",
    "patient_date_of_birth",
    "total_charges",
    "billing_provider_npi",
    "diagnosis_1",
    # Checkbox items: BDA is least reliable here, so uncertain values are flagged rather than trusted.
    "insurance_program",
    "another_health_benefit_plan_indicator",
    "condition_related_to_employment",
    "condition_related_to_auto_accident",
    "condition_related_to_other_accident",
    "accept_assignment",
)
# Items that older form layouts (or older blueprint versions) may not have; flag only when present but uncertain.
OPTIONAL_KEY_FIELDS = {
    "condition_related_to_employment",
    "condition_related_to_auto_accident",
    "condition_related_to_other_accident",
    "accept_assignment",
}


def classify(blueprint_name: str | None) -> str:
    name = (blueprint_name or "").lower()
    for token, cls in _CLASS_BY_TOKEN.items():
        if token in name:
            return cls
    return "OTHER"


def _confidence(explain: Any) -> float | None:
    if isinstance(explain, dict) and isinstance(explain.get("confidence"), (int, float)):
        return round(float(explain["confidence"]), 3)
    return None


def flatten_fields(inference: dict[str, Any], explain: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Top-level scalar fields with confidence. Arrays are handled separately."""
    out: dict[str, dict[str, Any]] = {}
    for name, value in (inference or {}).items():
        if isinstance(value, (list, dict)):
            continue
        out[name] = {"value": value, "confidence": _confidence((explain or {}).get(name))}
    return out


def _line_value(item: dict[str, Any], key: str) -> Any:
    value = item.get(key) if not isinstance(item.get(key), dict) else item[key].get("value")
    return None if isinstance(value, str) and not value.strip() else value  # BDA uses "" for empty fields


def service_lines(inference: dict[str, Any]) -> list[dict[str, Any]]:
    lines = []
    for i, item in enumerate(inference.get("medical_procedures") or [], start=1):
        if not isinstance(item, dict) or not (
            _line_value(item, "procedure_code") or _line_value(item, "charge_amount")
        ):
            continue
        lines.append(
            {
                "line_number": i,
                "service_start_date": _line_value(item, "service_start_date"),
                "service_end_date": _line_value(item, "service_end_date"),
                "place_of_service": _line_value(item, "place_of_service"),
                "procedure_code": _line_value(item, "procedure_code"),
                "procedure_description": _line_value(item, "procedure_description"),
                "modifiers": _line_value(item, "procedure_modifier"),
                "diagnosis_pointer": _line_value(item, "diagnosis_code"),
                "units": _line_value(item, "units"),
                "charge_amount": _line_value(item, "charge_amount"),
                "rendering_provider_npi": _line_value(item, "rendering_provider_npi"),
                "rendering_provider_other_id": _line_value(item, "rendering_provider_other_id"),
                "emg_indicator": _line_value(item, "emg_indicator"),
                "supplemental_information": _line_value(item, "supplemental_information"),
            }
        )
    return lines


def segment_record(custom_output: dict[str, Any], source_key: str) -> dict[str, Any]:
    matched = custom_output.get("matched_blueprint") or {}
    explain_list = custom_output.get("explainability_info") or [{}]
    explain = explain_list[0] if explain_list else {}
    inference = custom_output.get("inference_result") or {}
    split = custom_output.get("split_document") or {}
    return {
        "document_class": classify(matched.get("name")),
        "blueprint_confidence": matched.get("confidence"),
        "source_key": source_key,
        "page_indices": [int(p) + 1 for p in split.get("page_indices") or []],
        "inference": inference,
        "fields": flatten_fields(inference, explain),
    }


def build_case(
    claim_id: str,
    provider: dict[str, Any],
    segments: list[dict[str, Any]],
    confidence_threshold: float,
) -> dict[str, Any]:
    forms = [s for s in segments if s["document_class"] == CMS1500]
    if not forms:
        raise ValueError("NoClaimForm: no CMS-1500 was recognized in the submitted documents")
    form = max(forms, key=lambda s: len(s["fields"]))

    def uncertain(name: str) -> bool:
        f = form["fields"].get(name)
        if f is None or f["value"] in (None, ""):
            return name not in OPTIONAL_KEY_FIELDS
        return (f["confidence"] or 0) < confidence_threshold

    low = sorted(name for name in KEY_FIELDS if uncertain(name))
    evidence = [
        {
            "document_class": s["document_class"],
            "source_key": s["source_key"],
            "page_indices": s["page_indices"],
            "fields": s["fields"]
            | {k: {"value": v, "confidence": None} for k, v in s["inference"].items() if isinstance(v, (list, dict))},
        }
        for s in segments
        if s is not form
    ]
    return {
        "claim_id": claim_id,
        "provider": provider,
        "cms1500_source_key": form["source_key"],
        "cms1500": form["fields"],
        "service_lines": service_lines(form["inference"]),
        "evidence": evidence,
        "low_confidence_fields": low,
    }
