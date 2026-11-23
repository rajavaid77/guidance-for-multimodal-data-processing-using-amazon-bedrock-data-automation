from types import SimpleNamespace

import pytest

from claims_agents.gateway import base_tool_name, select_tools
from claims_agents.kb import make_retrieve_policy_tool
from claims_agents.models import (
    AdjudicationResult,
    ClaimCase,
    ClinicalResult,
    EligibilityResult,
    Finding,
    LineDecision,
    ValidationResult,
)
from claims_agents.specialists import load_prompt
from claims_agents.supervisor import ClaimReview, SpecialistToolkit

CASE = {
    "claim_id": "CLM-" + "a" * 32,
    "provider": {"provider_id": "PRV-1001", "npi": "1234567893", "name": "Any City Spine"},
    "cms1500": {"insured_id_number": {"value": "11-2234-10190", "confidence": 0.98}},
    "service_lines": [
        {"line_number": 1, "procedure_code": "97810", "charge_amount": 170.0},
        {"line_number": 2, "procedure_code": "98940", "charge_amount": 120.0},
    ],
}


def stub_runner(results):
    calls = []

    def runner(*, name, output_model, **_):
        calls.append(name)
        value = results[name]
        if isinstance(value, Exception):
            raise value
        return value

    runner.calls = calls
    return runner


def toolkit(runner):
    return SpecialistToolkit(
        reasoning_model=None,
        fast_model=None,
        validation_tools=[],
        eligibility_tools=[],
        clinical_tools=[],
        adjudication_tools=[],
        model_ids={"reasoning": "r", "fast": "f"},
        runner=runner,
    )


def approve_all():
    return AdjudicationResult(
        decision="APPROVE",
        confidence=0.95,
        rationale="All lines supported.",
        line_decisions=[LineDecision(line_number=i, decision="APPROVE", reason="ok") for i in (1, 2)],
    )


def run_all_tools(review):
    for t in review.build_tools():
        t()


def test_clean_claim_is_approved():
    runner = stub_runner(
        {
            "validation": ValidationResult(passed=True),
            "eligibility": EligibilityResult(
                passed=True, member_found=True, plan_name="AnyHealth Plus", coverage_active_on_all_dates=True
            ),
            "clinical": ClinicalResult(passed=True),
            "adjudication": approve_all(),
        }
    )
    review = ClaimReview(ClaimCase.model_validate(CASE), toolkit(runner), "1")
    run_all_tools(review)
    rec = review.assemble("summary")
    assert runner.calls == ["validation", "eligibility", "clinical", "adjudication"]
    assert rec.decision == "APPROVE" and rec.all_checks_passed and rec.confidence == 0.95


def test_approval_with_error_finding_is_downgraded_to_pend():
    err = Finding(code="INVALID_NPI", severity="ERROR", category="VALIDATION", message="bad npi")
    runner = stub_runner(
        {
            "validation": ValidationResult(passed=False, findings=[err]),
            "eligibility": EligibilityResult(passed=True, member_found=True),
            "clinical": ClinicalResult(passed=True),
            "adjudication": approve_all(),
        }
    )
    review = ClaimReview(ClaimCase.model_validate(CASE), toolkit(runner), "1")
    run_all_tools(review)
    rec = review.assemble("")
    assert rec.decision == "PEND"
    assert not rec.checks.validation
    assert any(f.code == "INVALID_NPI" for f in rec.findings)


def test_specialist_failure_pends_every_line():
    runner = stub_runner(
        {
            "validation": ValidationResult(passed=True),
            "eligibility": EligibilityResult(passed=True, member_found=True),
            "clinical": RuntimeError("boom"),
            "adjudication": RuntimeError("boom"),
        }
    )
    review = ClaimReview(ClaimCase.model_validate(CASE), toolkit(runner), "1")
    run_all_tools(review)
    rec = review.assemble("")
    assert rec.decision == "PEND"
    assert [d.decision for d in rec.line_decisions] == ["PEND", "PEND"]
    assert sum(f.code == "SPECIALIST_FAILED" for f in rec.findings) == 2


def test_low_confidence_extraction_caps_confidence():
    case = dict(CASE, low_confidence_fields=["insured_id_number"])
    runner = stub_runner(
        {
            "validation": ValidationResult(passed=True),
            "eligibility": EligibilityResult(passed=True, member_found=True),
            "clinical": ClinicalResult(passed=True),
            "adjudication": approve_all(),
        }
    )
    review = ClaimReview(ClaimCase.model_validate(case), toolkit(runner), "1")
    run_all_tools(review)
    assert review.assemble("").confidence == 0.7


def test_gateway_tool_selection_strips_target_prefix():
    tools = [SimpleNamespace(tool_name=n) for n in ("claims-tools___validate_codes", "claims-tools___save_decision")]
    assert base_tool_name("claims-tools___validate_codes") == "validate_codes"
    assert [t.tool_name for t in select_tools(tools, ["save_decision"])] == ["claims-tools___save_decision"]
    with pytest.raises(RuntimeError):
        select_tools(tools, ["check_eligibility"])


def test_retrieve_policy_filters_to_member_plan():
    class FakeKb:
        def retrieve(self, **kwargs):
            assert kwargs["knowledgeBaseId"] == "KB1"
            return {
                "retrievalResults": [
                    {
                        "location": {"s3Location": {"uri": "s3://b/eoc/Evidence_of_Coverage_-_AnyHealth_Plus.pdf"}},
                        "metadata": {"x-amz-bedrock-kb-document-page-number": 12.0},
                        "score": 0.81,
                        "content": {"text": "Acupuncture: 12 visits per year"},
                    },
                    {
                        "location": {"s3Location": {"uri": "s3://b/eoc/Evidence_of_Coverage_-_AnyHealth_Premium.pdf"}},
                        "metadata": {},
                        "score": 0.8,
                        "content": {"text": "other plan"},
                    },
                ]
            }

    retrieve_policy = make_retrieve_policy_tool("KB1", "us-west-2", client=FakeKb())
    passages = retrieve_policy(query="acupuncture", plan_name="AnyHealth Plus")
    assert len(passages) == 1 and passages[0]["page"] == 12


@pytest.mark.parametrize("name", ["supervisor", "validation", "eligibility", "clinical", "adjudication"])
def test_prompts_load(name):
    assert len(load_prompt(name)) > 200


def test_bda_blank_strings_are_accepted():
    case = dict(
        CASE,
        service_lines=[
            {
                "line_number": 1,
                "units": "",
                "charge_amount": "$1,170.50",
                "place_of_service": 11,
                "diagnosis_pointer": "",
            }
        ],
    )
    line = ClaimCase.model_validate(case).service_lines[0]
    assert line.units is None and line.charge_amount == 1170.5
    assert line.place_of_service == "11" and line.diagnosis_pointer is None


def test_retrieve_policy_keeps_shared_policies():
    class FakeKb:
        def retrieve(self, **kwargs):
            return {
                "retrievalResults": [
                    {
                        "location": {"s3Location": {"uri": "s3://b/policies/common/AP-150_Telehealth_Services.md"}},
                        "metadata": {},
                        "score": 0.7,
                        "content": {"text": "POS 02 or 10"},
                    },
                    {
                        "location": {
                            "s3Location": {"uri": "s3://b/policies/plans/AnyHealth_Standard_Schedule_of_Benefits.md"}
                        },
                        "metadata": {},
                        "score": 0.6,
                        "content": {"text": "other plan"},
                    },
                ]
            }

    passages = make_retrieve_policy_tool("KB1", "us-west-2", client=FakeKb())(
        query="telehealth", plan_name="AnyHealth Plus"
    )
    assert [p["text"] for p in passages] == ["POS 02 or 10"]


def test_structured_summary_fields_pass_through():
    from claims_agents.models import SupervisorSummary

    runner = stub_runner(
        {
            "validation": ValidationResult(passed=True),
            "eligibility": EligibilityResult(passed=True, member_found=True),
            "clinical": ClinicalResult(passed=True),
            "adjudication": approve_all(),
        }
    )
    review = ClaimReview(ClaimCase.model_validate(CASE), toolkit(runner), "1")
    run_all_tools(review)
    rec = review.assemble(
        SupervisorSummary(
            headline="Approve both lines.",
            key_points=["a", "b"],
            verify_before_payment=["item 10b"],
            summary="s",
            specialists_completed=[],
        )
    )
    assert (
        rec.headline == "Approve both lines."
        and rec.key_points == ["a", "b"]
        and rec.verify_before_payment == ["item 10b"]
    )


def test_each_review_run_gets_a_fresh_memory_session():
    from claims_agents.main import review_session_id

    a, b = review_session_id("CLM-x"), review_session_id("CLM-x")
    assert a != b and a.startswith("CLM-x-")
