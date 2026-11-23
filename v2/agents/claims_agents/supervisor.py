"""Supervisor agent: delegates to specialists exposed as tools (agents-as-tools) and assembles the Recommendation."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel
from strands import Agent, tool

from .models import (
    AdjudicationResult,
    Checks,
    ClaimCase,
    ClinicalResult,
    EligibilityResult,
    Finding,
    LineDecision,
    Recommendation,
    SupervisorSummary,
    ValidationResult,
)
from .specialists import load_prompt, run_specialist

logger = logging.getLogger(__name__)

LOW_CONFIDENCE_CAP = 0.7


@dataclass
class SpecialistToolkit:
    """Models and tools each specialist needs. Injected so tests can stub them."""

    reasoning_model: Any
    fast_model: Any
    validation_tools: list[Any]
    eligibility_tools: list[Any]
    clinical_tools: list[Any]
    adjudication_tools: list[Any]
    model_ids: dict[str, str] = field(default_factory=dict)
    runner: Callable[..., BaseModel] = run_specialist


class ClaimReview:
    """One review of one claim. Holds specialist results so the final output never depends on LLM paraphrase."""

    def __init__(self, case: ClaimCase, toolkit: SpecialistToolkit, prompt_version: str):
        self.case = case
        self.toolkit = toolkit
        self.prompt_version = prompt_version
        self.validation: ValidationResult | None = None
        self.eligibility: EligibilityResult | None = None
        self.clinical: ClinicalResult | None = None
        self.adjudication: AdjudicationResult | None = None
        self.errors: list[Finding] = []

    # ----- specialist calls -----
    def _call(self, name: str, model: Any, tools: list[Any], payload: dict[str, Any], output, instruction: str):
        try:
            return self.toolkit.runner(
                name=name, model=model, tools=tools, payload=payload, output_model=output, instruction=instruction
            )
        except Exception as exc:  # recorded as a finding; adjudication guard will pend the claim
            logger.exception("Specialist %s failed", name)
            self.errors.append(
                Finding(
                    code="SPECIALIST_FAILED",
                    severity="ERROR",
                    category="ADJUDICATION",
                    message=f"{name} specialist failed: {type(exc).__name__}",
                )
            )
            return None

    def _case_payload(self) -> dict[str, Any]:
        return self.case.model_dump(mode="json")

    def build_tools(self) -> list[Any]:
        review = self

        @tool
        def run_validation() -> dict:
            """Validate CMS-1500 data quality, codes, NPIs and duplicates. Call first."""
            review.validation = review._call(
                "validation",
                review.toolkit.fast_model,
                review.toolkit.validation_tools,
                review._case_payload(),
                ValidationResult,
                "Validate this claim.",
            )
            return review.validation.model_dump() if review.validation else {"error": "validation failed"}

        @tool
        def run_eligibility() -> dict:
            """Check member eligibility, coverage on dates of service and coordination of benefits. Call second."""
            review.eligibility = review._call(
                "eligibility",
                review.toolkit.fast_model,
                review.toolkit.eligibility_tools,
                review._case_payload(),
                EligibilityResult,
                "Check eligibility for this claim.",
            )
            return review.eligibility.model_dump() if review.eligibility else {"error": "eligibility failed"}

        @tool
        def run_clinical_review() -> dict:
            """Reconcile billed lines with evidence and check medical necessity and plan coverage. Call third."""
            payload = review._case_payload()
            payload["plan_name"] = review.eligibility.plan_name if review.eligibility else None
            review.clinical = review._call(
                "clinical",
                review.toolkit.reasoning_model,
                review.toolkit.clinical_tools,
                payload,
                ClinicalResult,
                "Review every service line of this claim.",
            )
            return review.clinical.model_dump() if review.clinical else {"error": "clinical review failed"}

        @tool
        def run_adjudication() -> dict:
            """Produce line-level decisions from all specialist results and save them. Call last."""
            payload = {
                "claim": review._case_payload(),
                "validation": review.validation.model_dump() if review.validation else None,
                "eligibility": review.eligibility.model_dump() if review.eligibility else None,
                "clinical": review.clinical.model_dump() if review.clinical else None,
                "specialist_errors": [e.model_dump() for e in review.errors],
            }
            review.adjudication = review._call(
                "adjudication",
                review.toolkit.reasoning_model,
                review.toolkit.adjudication_tools,
                payload,
                AdjudicationResult,
                f"Adjudicate claim {review.case.claim_id} and call save_decision with your result.",
            )
            return review.adjudication.model_dump() if review.adjudication else {"error": "adjudication failed"}

        return [run_validation, run_eligibility, run_clinical_review, run_adjudication]

    # ----- orchestration -----
    def run(self, session_manager: Any = None) -> Recommendation:
        supervisor = Agent(
            name="supervisor",
            model=self.toolkit.reasoning_model,
            system_prompt=load_prompt("supervisor"),
            tools=self.build_tools(),
            structured_output_model=SupervisorSummary,
            session_manager=session_manager,
            callback_handler=None,
            trace_attributes={"claims.claim_id": self.case.claim_id},
        )
        summary: SupervisorSummary | None = None
        try:
            result = supervisor(f"Review claim {self.case.claim_id}. Run all four specialists, then summarize.")
            if isinstance(result.structured_output, SupervisorSummary):
                summary = result.structured_output
        except Exception as exc:
            logger.exception("Supervisor failed")
            self.errors.append(
                Finding(
                    code="SUPERVISOR_FAILED",
                    severity="ERROR",
                    category="ADJUDICATION",
                    message=f"Supervisor failed: {type(exc).__name__}",
                )
            )
        return self.assemble(summary)

    def assemble(self, summary: SupervisorSummary | str | None) -> Recommendation:
        """Deterministic guardrails over the LLM decision."""
        findings: list[Finding] = []
        for part in (self.validation, self.eligibility, self.clinical):
            if part is not None:
                findings.extend(part.findings)
        findings.extend(self.errors)

        checks = Checks(
            validation=bool(self.validation and self.validation.passed),
            eligibility=bool(self.eligibility and self.eligibility.passed),
            clinical=bool(self.clinical and self.clinical.passed),
        )
        all_passed = checks.validation and checks.eligibility and checks.clinical and not self.errors

        if self.adjudication is None:
            decision, confidence, rationale = "PEND", 0.0, "Adjudication did not complete; manual review required."
            line_decisions = [
                LineDecision(line_number=line.line_number, decision="PEND", reason="Automated review incomplete")
                for line in self.case.service_lines
            ]
        else:
            decision = self.adjudication.decision
            confidence = self.adjudication.confidence
            rationale = self.adjudication.rationale
            line_decisions = self.adjudication.line_decisions

        has_error = any(f.severity == "ERROR" for f in findings)
        if decision == "APPROVE" and (has_error or not all_passed):
            decision = "PEND"
            rationale = f"Downgraded to PEND: approval conflicts with failed checks. {rationale}"
        if self.case.low_confidence_fields:
            confidence = min(confidence, LOW_CONFIDENCE_CAP)

        if isinstance(summary, str):  # plain text (tests / fallback)
            summary = SupervisorSummary(headline="", summary=summary, specialists_completed=[]) if summary else None
        summary_text = summary.summary if summary else ""
        return Recommendation(
            claim_id=self.case.claim_id,
            decision=decision,
            confidence=round(confidence, 3),
            all_checks_passed=all_passed,
            checks=checks,
            line_decisions=line_decisions,
            findings=findings,
            summary=summary_text or rationale,
            headline=summary.headline if summary else "",
            key_points=summary.key_points if summary else [],
            verify_before_payment=summary.verify_before_payment if summary else [],
            rationale=rationale,
            models=self.toolkit.model_ids,
            prompt_version=self.prompt_version,
        )
