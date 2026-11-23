import pytest

from workflow.bda_output import build_case, classify, segment_record
from workflow.routing import route


def custom_output(blueprint, inference, explain=None, pages=(0,)):
    return {
        "matched_blueprint": {"name": blueprint, "confidence": 0.97},
        "inference_result": inference,
        "explainability_info": [explain or {}],
        "split_document": {"page_indices": list(pages)},
    }


FORM = {
    "insured_id_number": "11-2234-10190",
    "patient_name": "Doe, John",
    "patient_date_of_birth": "1960-10-10",
    "total_charges": 660.0,
    "billing_provider_npi": "1234567890",
    "diagnosis_1": "M54.9",
    "medical_procedures": [
        {"service_start_date": "2005-11-04", "procedure_code": "97810", "charge_amount": 170.0, "diagnosis_code": "A"},
        {"procedure_code": None, "charge_amount": None},
    ],
}
FORM["insurance_program"] = "GROUP_HEALTH_PLAN"
FORM["another_health_benefit_plan_indicator"] = "NO"
EXPLAIN = {k: {"confidence": 0.95} for k in FORM if k != "medical_procedures"} | {"diagnosis_1": {"confidence": 0.5}}


def test_classify_by_blueprint_suffix():
    assert classify("agentic-claims-cms1500") == "CMS1500"
    assert classify("agentic-claims-medical-record") == "MEDICAL_RECORD"
    assert classify(None) == "OTHER"


def test_build_case_from_segments():
    form = segment_record(custom_output("p-cms1500", FORM, EXPLAIN), "claims/c/docs/01-form.pdf")
    note = segment_record(
        custom_output(
            "p-medical-record", {"encounter_date": "2005-11-04", "diagnoses": [{"code": "M54.9"}]}, pages=(0, 1)
        ),
        "claims/c/docs/02-note.pdf",
    )
    case = build_case("CLM-x", {"provider_id": "P", "npi": "1", "name": "n"}, [form, note], 0.8)
    assert case["cms1500"]["insured_id_number"]["value"] == "11-2234-10190"
    assert [line["procedure_code"] for line in case["service_lines"]] == ["97810"]  # empty line dropped
    assert case["low_confidence_fields"] == ["diagnosis_1"]  # optional checkbox items absent -> not flagged
    assert case["evidence"][0]["page_indices"] == [1, 2]
    assert case["evidence"][0]["fields"]["diagnoses"]["value"] == [{"code": "M54.9"}]


def test_build_case_requires_claim_form():
    note = segment_record(custom_output("p-medical-record", {}), "k")
    with pytest.raises(ValueError, match="NoClaimForm"):
        build_case("CLM-x", {}, [note], 0.8)


@pytest.mark.parametrize(
    "rec,total,expected",
    [
        ({"decision": "APPROVE", "all_checks_passed": True, "confidence": 0.95}, 500, "AUTO"),
        ({"decision": "APPROVE", "all_checks_passed": True, "confidence": 0.95}, 5000, "REVIEW"),
        ({"decision": "APPROVE", "all_checks_passed": True, "confidence": 0.7}, 100, "REVIEW"),
        ({"decision": "APPROVE", "all_checks_passed": False, "confidence": 0.99}, 100, "REVIEW"),
        ({"decision": "DENY", "all_checks_passed": True, "confidence": 0.99}, 100, "REVIEW"),
        ({"decision": "APPROVE", "all_checks_passed": True, "confidence": 0.99}, None, "REVIEW"),
    ],
)
def test_routing_never_auto_denies(rec, total, expected):
    assert route(rec, total, 1000, 0.9, 1500)[0] == expected
