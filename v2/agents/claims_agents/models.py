"""Typed contracts shared by the workflow, the agents and the examiner UI."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

Severity = Literal["INFO", "WARNING", "ERROR"]
Decision = Literal["APPROVE", "DENY", "PEND"]


# ---------- input: claim case assembled by the workflow from BDA output ----------
class ExtractedField(BaseModel):
    value: Any = None
    confidence: float | None = None


class ServiceLine(BaseModel):
    line_number: int
    service_start_date: str | None = None
    service_end_date: str | None = None
    place_of_service: str | None = None
    procedure_code: str | None = None
    procedure_description: str | None = None
    modifiers: str | None = None
    diagnosis_pointer: str | None = None
    units: float | None = None
    charge_amount: float | None = None
    rendering_provider_npi: str | None = None
    rendering_provider_other_id: str | None = None
    emg_indicator: str | None = None
    supplemental_information: str | None = Field(
        default=None, description="Shaded-row supplemental data (e.g. NDC N4..., anesthesia time); not service data"
    )

    @field_validator("*", mode="before")
    @classmethod
    def _blank_to_none(cls, value: Any) -> Any:
        """BDA returns "" for empty fields; amounts may carry "$" and thousands separators."""
        if isinstance(value, str):
            value = value.strip()
            if value == "":
                return None
        return value

    @field_validator("units", "charge_amount", mode="before")
    @classmethod
    def _number(cls, value: Any) -> Any:
        if isinstance(value, str):
            try:
                return float(value.replace("$", "").replace(",", ""))
            except ValueError:
                return None
        return value

    @field_validator(
        "service_start_date",
        "service_end_date",
        "place_of_service",
        "procedure_code",
        "modifiers",
        "diagnosis_pointer",
        "rendering_provider_npi",
        "rendering_provider_other_id",
        "emg_indicator",
        "supplemental_information",
        mode="before",
    )
    @classmethod
    def _text(cls, value: Any) -> Any:
        return None if value is None else str(value)


class EvidenceDocument(BaseModel):
    document_class: str
    source_key: str
    page_indices: list[int] = Field(default_factory=list)
    fields: dict[str, ExtractedField] = Field(default_factory=dict)


class SubmittingProvider(BaseModel):
    provider_id: str
    npi: str
    name: str


class ClaimCase(BaseModel):
    claim_id: str
    provider: SubmittingProvider
    cms1500_source_key: str | None = None
    cms1500: dict[str, ExtractedField] = Field(default_factory=dict)
    service_lines: list[ServiceLine] = Field(default_factory=list)
    evidence: list[EvidenceDocument] = Field(default_factory=list)
    low_confidence_fields: list[str] = Field(default_factory=list)


# ---------- specialist outputs ----------
class Citation(BaseModel):
    source: str = Field(description="S3 key of the claim document, or the policy document URI from the knowledge base")
    page: int | None = Field(default=None, description="1-based page number when known")
    excerpt: str = Field(description="Short verbatim excerpt that supports the finding")


class Finding(BaseModel):
    code: str = Field(description="Short machine-readable code, e.g. INVALID_NPI, NOT_COVERED, NO_DOCUMENTATION")
    severity: Severity
    category: Literal["VALIDATION", "ELIGIBILITY", "CLINICAL", "ADJUDICATION"]
    message: str
    line_number: int | None = None
    citations: list[Citation] = Field(default_factory=list)


class ValidationResult(BaseModel):
    passed: bool = Field(description="False if any ERROR finding exists")
    findings: list[Finding] = Field(default_factory=list)


class EligibilityResult(BaseModel):
    passed: bool
    member_found: bool
    plan_name: str | None = None
    coverage_active_on_all_dates: bool = False
    other_coverage_primary: bool = Field(default=False, description="True if another payer is primary (COB)")
    findings: list[Finding] = Field(default_factory=list)


class LineAssessment(BaseModel):
    line_number: int
    supported_by_evidence: bool
    medically_necessary: Literal["YES", "NO", "UNCLEAR"]
    covered_by_plan: Literal["YES", "NO", "UNCLEAR"]
    rationale: str
    citations: list[Citation] = Field(default_factory=list)


class ClinicalResult(BaseModel):
    passed: bool
    line_assessments: list[LineAssessment] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)


class LineDecision(BaseModel):
    line_number: int
    decision: Decision
    carc: str | None = Field(default=None, description="Claim Adjustment Reason Code when not APPROVE, e.g. 50, 96, 16")
    rarc: str | None = Field(default=None, description="Remittance Advice Remark Code, e.g. N115, M127")
    reason: str


class AdjudicationResult(BaseModel):
    decision: Decision
    confidence: float = Field(ge=0.0, le=1.0)
    line_decisions: list[LineDecision] = Field(default_factory=list)
    rationale: str


class SupervisorSummary(BaseModel):
    headline: str = Field(description="One sentence, at most 25 words: the recommended outcome and the main reason")
    key_points: list[str] = Field(
        default_factory=list,
        description="3-5 short bullet points (each <= 25 words) an examiner must know, most important first",
    )
    verify_before_payment: list[str] = Field(
        default_factory=list,
        description="Items a person should confirm before payment (e.g. low-confidence form fields); empty if none",
    )
    summary: str = Field(description="Plain-language summary for the claims examiner, 3-6 sentences")
    specialists_completed: list[Literal["validation", "eligibility", "clinical_review", "adjudication"]]


# ---------- final output returned to Step Functions ----------
class Checks(BaseModel):
    validation: bool
    eligibility: bool
    clinical: bool


class Recommendation(BaseModel):
    claim_id: str
    decision: Decision
    confidence: float
    all_checks_passed: bool
    checks: Checks
    line_decisions: list[LineDecision]
    findings: list[Finding]
    summary: str
    headline: str = ""
    key_points: list[str] = Field(default_factory=list)
    verify_before_payment: list[str] = Field(default_factory=list)
    rationale: str
    models: dict[str, str]
    prompt_version: str
