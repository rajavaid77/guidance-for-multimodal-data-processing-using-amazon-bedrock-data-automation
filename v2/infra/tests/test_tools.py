import datetime as dt

from fakes import FakeDb, install

from tools import check_eligibility, save_decision, validate_codes
from tools.codes import normalize_code, normalize_icd10, npi_is_valid, parse_date


def test_npi_check_digit():
    assert npi_is_valid("1234567893")
    assert npi_is_valid("1245319599")
    assert not npi_is_valid("1234567890")  # the NPI printed on the sample forms
    assert not npi_is_valid("123")


def test_code_normalization_and_dates():
    assert normalize_code("97810/Acupuncture") == "97810"
    assert normalize_icd10("m549") == "M54.9"
    assert normalize_icd10("M25.552 - Pain in left hip") == "M25.552"
    assert parse_date("11/04/2005") == dt.date(2005, 11, 4)
    assert parse_date("2020-03-11") == dt.date(2020, 3, 11)
    assert parse_date("garbage") is None


def test_validate_codes_flags_format_and_reference(monkeypatch):
    fake = FakeDb(
        {
            "FROM ref_icd10": [{"code": "M54.9", "description": "Dorsalgia"}],
            "FROM ref_procedure": [{"code": "97810", "description": "Acupuncture", "max_units_per_day": 1}],
            "FROM providers": [{"provider_id": "PRV-1001", "npi": "1234567893", "name": "X", "in_network": True}],
        }
    )
    install(monkeypatch, validate_codes, fake)
    out = validate_codes.handler(
        {
            "icd10_codes": ["M54.9", "M99.99", "BAD"],
            "procedure_codes": ["97810", "9X"],
            "npis": ["1234567890", "1234567893"],
        },
        None,
    )
    icd = {r["code"]: r for r in out["icd10"]}
    assert icd["M54.9"]["in_reference_set"] and not icd["M99.99"]["in_reference_set"]
    assert icd["BAD"]["valid_format"] is False
    procs = {r["code"]: r for r in out["procedures"]}
    assert procs["97810"]["max_units_per_day"] == 1 and procs["9X"]["valid_format"] is False
    npis = {r["npi"]: r for r in out["npis"]}
    assert (
        npis["1234567890"]["check_digit_valid"] is False and npis["1234567893"]["provider"]["provider_id"] == "PRV-1001"
    )


def test_eligibility_matches_dependent_and_dates(monkeypatch):
    fake = FakeDb(
        {
            "FROM members m JOIN plans": [
                {
                    "member_id": 1,
                    "insured_name": "Jane Doe",
                    "birth_date": "1965-06-12",
                    "group_number": "G4683A",
                    "coverage_start": "2000-01-01",
                    "coverage_end": None,
                    "plan_name": "AnyHealth Plus",
                    "deductible": 500,
                    "coinsurance_pct": 20,
                    "eoc_document_key": "eoc/x.pdf",
                }
            ],
            "FROM patients": [
                {
                    "first_name": "John",
                    "last_name": "Doe",
                    "birth_date": "1960-10-10",
                    "relationship_to_insured": "Spouse",
                }
            ],
            "FROM other_coverage": [],
        }
    )
    install(monkeypatch, check_eligibility, fake)
    out = check_eligibility.handler(
        {
            "insured_id_number": "11-2234-10190",
            "patient_name": "Doe, John",
            "patient_date_of_birth": "10/10/1960",
            "service_dates": ["11/04/2005", "1999-12-31"],
        },
        None,
    )
    assert out["member_found"] and out["plan_name"] == "AnyHealth Plus"
    assert out["patient_match"]["dob_matches"] is True
    assert [d["coverage_active"] for d in out["service_dates"]] == [True, False]


def test_eligibility_unknown_member(monkeypatch):
    install(monkeypatch, check_eligibility, FakeDb())
    assert check_eligibility.handler({"insured_id_number": "nope"}, None)["member_found"] is False


def test_save_decision_only_for_claims_under_agent_review(monkeypatch):
    fake = FakeDb(updated={"UPDATE claims": 0})
    install(monkeypatch, save_decision, fake)
    out = save_decision.handler(
        {"claim_id": "CLM-1", "decision": "APPROVE", "confidence": 0.9, "line_decisions": []}, None
    )
    assert out == {"saved": False, "error": "claim is not under agent review"}
    assert save_decision.handler({"claim_id": "CLM-1", "decision": "MAYBE"}, None)["saved"] is False


def test_save_decision_attributes_to_current_run(monkeypatch):
    fake = FakeDb()
    install(monkeypatch, save_decision, fake)
    out = save_decision.handler({"claim_id": "CLM-1", "decision": "PEND", "confidence": 0.5}, None)
    assert out["saved"] is True
    insert = next(c for c in fake.calls if "INSERT INTO decisions" in c[0])[0]
    assert "claim_run_id" in insert and "SELECT current_run FROM claims" in insert


def test_find_duplicates_reports_detail_and_processed_flag(monkeypatch):
    from tools import find_duplicates

    fake = FakeDb(
        {
            "FROM service_lines sl JOIN claims": [
                {
                    "claim_id": "CLM-a",
                    "status": "PENDING_REVIEW",
                    "provider_id": "PRV-1001",
                    "final_decision": None,
                    "line_number": 1,
                    "modifiers": "25",
                    "units": 1,
                    "charge_amount": 125.35,
                },
                {
                    "claim_id": "CLM-b",
                    "status": "APPROVED",
                    "provider_id": "PRV-1001",
                    "final_decision": "APPROVE",
                    "line_number": 1,
                    "modifiers": "25",
                    "units": 1,
                    "charge_amount": 125.35,
                },
            ]
        }
    )
    install(monkeypatch, find_duplicates, fake)
    out = find_duplicates.handler(
        {
            "claim_id": "CLM-x",
            "insured_id_number": "123456789A",
            "service_lines": [{"service_date": "2025-01-07", "procedure_code": "99214"}],
        },
        None,
    )
    existing = out["matches"][0]["existing"]
    assert [e["processed"] for e in existing] == [False, True] and existing[0]["modifiers"] == "25"
