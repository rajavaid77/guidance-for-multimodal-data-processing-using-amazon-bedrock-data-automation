"""MCP tool schemas for the AgentCore Gateway Lambda targets (must match lambdas/tools/*)."""

from __future__ import annotations

from aws_cdk import aws_bedrockagentcore as agentcore

S = agentcore.SchemaDefinition
T = agentcore.SchemaDefinitionType


def _str(desc: str) -> S:
    return S(type=T.STRING, description=desc)


def _str_list(desc: str) -> S:
    return S(type=T.ARRAY, description=desc, items=S(type=T.STRING))


def _obj(props: dict[str, S], required: list[str] | None = None, desc: str | None = None) -> S:
    return S(type=T.OBJECT, properties=props, required=required or [], description=desc)


TOOLS: dict[str, agentcore.ToolDefinition] = {
    "validate_codes": agentcore.ToolDefinition(
        name="validate_codes",
        description="Validate ICD-10 diagnosis codes, CPT/HCPCS procedure codes, place of service codes, modifiers and "
        "NPIs. Returns format validity, reference-set membership, descriptions and provider records.",
        input_schema=_obj(
            {
                "icd10_codes": _str_list("ICD-10-CM codes from item 21"),
                "procedure_codes": _str_list("CPT or HCPCS codes from item 24D"),
                "pos_codes": _str_list("Place of service codes from item 24B"),
                "modifiers": _str_list("Procedure modifiers from item 24D"),
                "npis": _str_list("NPIs from items 24J and 33a"),
            }
        ),
    ),
    "check_eligibility": agentcore.ToolDefinition(
        name="check_eligibility",
        description="Look up a member by insured ID, match the patient, check coverage on each date of service and "
        "list other coverage for coordination of benefits.",
        input_schema=_obj(
            {
                "insured_id_number": _str("Insured ID from item 1a"),
                "patient_name": _str("Patient name from item 2"),
                "patient_date_of_birth": _str("Patient date of birth from item 3"),
                "service_dates": _str_list("Every date of service on the claim"),
            },
            required=["insured_id_number", "service_dates"],
        ),
    ),
    "find_duplicates": agentcore.ToolDefinition(
        name="find_duplicates",
        description="Find service lines already billed on other claims for the same member, date and procedure.",
        input_schema=_obj(
            {
                "claim_id": _str("Current claim id, excluded from the search"),
                "insured_id_number": _str("Insured ID from item 1a"),
                "service_lines": S(
                    type=T.ARRAY,
                    description="Service lines to check",
                    items=_obj(
                        {
                            "service_date": _str("Date of service"),
                            "procedure_code": _str("CPT or HCPCS code"),
                            "charge_amount": S(type=T.NUMBER, description="Billed charge"),
                        }
                    ),
                ),
            },
            required=["claim_id", "insured_id_number", "service_lines"],
        ),
    ),
    "save_decision": agentcore.ToolDefinition(
        name="save_decision",
        description="Persist the adjudication recommendation for a claim that is currently under agent review.",
        input_schema=_obj(
            {
                "claim_id": _str("Claim id"),
                "decision": _str("APPROVE, DENY or PEND"),
                "confidence": S(type=T.NUMBER, description="Confidence between 0 and 1"),
                "rationale": _str("Short rationale"),
                "line_decisions": S(
                    type=T.ARRAY,
                    description="Line-level decisions",
                    items=_obj(
                        {
                            "line_number": S(type=T.INTEGER, description="Service line number"),
                            "decision": _str("APPROVE, DENY or PEND"),
                            "carc": _str("Claim adjustment reason code"),
                            "rarc": _str("Remittance advice remark code"),
                            "reason": _str("Short reason"),
                        },
                        required=["line_number", "decision", "reason"],
                    ),
                ),
            },
            required=["claim_id", "decision", "confidence", "rationale", "line_decisions"],
        ),
    ),
}
