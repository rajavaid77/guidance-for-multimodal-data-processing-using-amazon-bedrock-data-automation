# Synthetic policy library (demo content)

These documents are **synthetic** and written for the agentic claims demo. They are not real payer policy,
CPT/HCPCS guidance or legal plan language. They complement the sample Evidence of Coverage PDFs in
`assets/data/claims_review/eoc/` and resolve ambiguities in them.

- `plans/` - one Schedule of Benefits per plan. File names contain the plan name (`AnyHealth_Plus`, ...) so the
  agents' policy search keeps only the member's plan.
- `common/` - medical and administrative policies that apply to every AnyHealth plan.

Order of precedence when documents disagree: Plan Schedule of Benefits > Medical/Administrative Policy >
Evidence of Coverage narrative.
