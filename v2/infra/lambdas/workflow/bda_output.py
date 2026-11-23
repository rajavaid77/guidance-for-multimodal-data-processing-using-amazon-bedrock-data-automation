"""Parse Bedrock Data Automation custom output into a ClaimCase (pure functions, unit tested)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

CMS1500, MEDICAL_RECORD, LAB_REPORT, PRIMARY_EOB = "CMS1500", "MEDICAL_RECORD", "LAB_REPORT", "PRIMARY_EOB"
DISCHARGE_SUMMARY, INSURANCE_CARD = "DISCHARGE_SUMMARY", "INSURANCE_CARD"
PRESCRIPTION_LABEL, DRIVER_LICENSE = "PRESCRIPTION_LABEL", "DRIVER_LICENSE"
INVOICE = "INVOICE"
# Matched against the lower-cased blueprint name with "_" and spaces turned into "-" (custom blueprints are named
# "<prefix>-<token>"; AWS-managed ones are "bedrock-data-automation-public-<token>").
_CLASS_BY_TOKEN = {
    "cms1500": CMS1500,
    "medical-record": MEDICAL_RECORD,
    "lab-report": LAB_REPORT,
    "primary-eob": PRIMARY_EOB,
    "discharge-summary": DISCHARGE_SUMMARY,
    "medical-insurance-card": INSURANCE_CARD,
    "prescription-label": PRESCRIPTION_LABEL,
    "driver-license": DRIVER_LICENSE,
    "invoice": INVOICE,
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
    name = (blueprint_name or "").lower().replace("_", "-").replace(" ", "-")
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


_TYPE_LABELS = {
    CMS1500: "CMS-1500 claim form",
    MEDICAL_RECORD: "Medical record",
    LAB_REPORT: "Lab report",
    PRIMARY_EOB: "Primary EOB",
    DISCHARGE_SUMMARY: "Discharge summary",
    INSURANCE_CARD: "Insurance card",
    PRESCRIPTION_LABEL: "Prescription label",
    DRIVER_LICENSE: "Driver license",
    INVOICE: "Invoice",
    "OTHER": "Other document",
}


def keep_best_form(entries: list[dict[str, Any]]) -> None:
    """A claim has one claim form. BDA can also match other pages (an invoice, a statement) to the CMS-1500 blueprint
    at a lower confidence. Within one file keep the most confident match as CMS1500 and call the rest OTHER."""
    forms = [e for e in entries if e["document_class"] == CMS1500]
    if len(forms) < 2:
        return
    best = max(forms, key=lambda e: e.get("blueprint_confidence") or 0)
    for entry in forms:
        if entry is not best:
            entry["document_class"] = "OTHER"


def standard_pages(standard_output: dict[str, Any]) -> list[int]:
    """1-based file pages of one segment, from its standard output (`metadata` range, else `pages[].page_index`)."""
    meta = standard_output.get("metadata") or {}
    start, end = meta.get("start_page_index"), meta.get("end_page_index")
    if isinstance(start, int) and isinstance(end, int) and end >= start:
        return list(range(start + 1, end + 2))
    indexes = [p.get("page_index") for p in standard_output.get("pages") or []]
    return sorted(int(i) + 1 for i in indexes if isinstance(i, int))


def parse_segments(
    job_metadata: dict[str, Any], asset_id: str, loader: Callable[[str], dict[str, Any]]
) -> list[dict[str, Any]]:
    """One entry per BDA segment of an asset, matched or not, with 1-based file page numbers.

    Segments without a blueprint match become class OTHER. BDA splits every file whether or not a blueprint
    matches, and records each segment's page range in its standard output (`metadata.start_page_index` /
    `end_page_index`, 0-based). Custom output carries `split_document.page_indices` for matched segments only, and
    those win when present because they can be non-contiguous. `job_metadata.json` has no `segment_index`; the
    position in `segment_metadata` is the segment index.
    """
    out: list[dict[str, Any]] = []
    for item in job_metadata.get("output_metadata") or []:
        if asset_id and str(item.get("asset_id")) != asset_id:
            continue
        first = len(out)
        for position, segment in enumerate(item.get("segment_metadata") or []):
            index = segment.get("segment_index", position)
            custom_path = segment.get("custom_output_path")
            standard_path = segment.get("standard_output_path")
            matched = bool(custom_path) and segment.get("custom_output_status", "MATCH") == "MATCH"
            blueprint, confidence, pages = None, None, []
            custom = loader(custom_path) if matched else None
            if custom:
                blueprint = (custom.get("matched_blueprint") or {}).get("name")
                confidence = (custom.get("matched_blueprint") or {}).get("confidence")
                pages = [int(p) + 1 for p in (custom.get("split_document") or {}).get("page_indices") or []]
            if not pages and standard_path:
                try:
                    pages = standard_pages(loader(standard_path))
                except Exception:  # noqa: BLE001 - an unreadable standard output leaves the range unknown
                    pages = []
            out.append(
                {
                    "segment_index": int(index),
                    "document_class": classify(blueprint) if matched else "OTHER",
                    "blueprint_confidence": confidence,
                    "page_indices": pages,
                    "custom_output_path": custom_path if matched else None,
                    "standard_output_path": standard_path,
                }
            )
        keep_best_form(out[first:])
    return out


def part_name(source_file_name: str, document_class: str, pages: list[int], multi: bool) -> str:
    if not multi:
        return source_file_name
    label = _TYPE_LABELS.get(document_class, _TYPE_LABELS["OTHER"])
    if not pages:
        return label
    first, last = min(pages), max(pages)
    return f"{label} (page {first})" if first == last else f"{label} (pages {first}-{last})"


def build_case(
    claim_id: str,
    provider: dict[str, Any],
    segments: list[dict[str, Any]],
    confidence_threshold: float,
) -> dict[str, Any]:
    forms = [s for s in segments if s["document_class"] == CMS1500]
    if not forms:
        raise ValueError("NoClaimForm: no CMS-1500 was recognized in the submitted documents")

    def filled(segment: dict[str, Any]) -> int:
        return sum(1 for f in segment["fields"].values() if f.get("value") not in (None, ""))

    form = max(forms, key=lambda s: (filled(s), s.get("blueprint_confidence") or 0))
    # Any other CMS-1500 match (e.g. an invoice with a similar layout) is not a second claim form: keep it as an
    # ordinary document without its mostly empty claim-form fields so the agents cannot mistake it for the form.
    segments = [
        s
        if s is form or s["document_class"] != CMS1500
        else s | {"document_class": "OTHER", "fields": {}, "inference": {}}
        for s in segments
    ]

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
