export type Decision = "APPROVE" | "DENY" | "PEND";

export interface ClaimSummary {
  claim_id: string;
  status: string;
  patient_name: string | null;
  total_charges: number | null;
  final_decision: Decision | null;
  created_at: string;
  updated_at: string;
}

export interface Citation {
  source: string;
  page: number | null;
  excerpt: string;
}

export interface Finding {
  code: string;
  severity: "INFO" | "WARNING" | "ERROR";
  category: string;
  message: string;
  line_number: number | null;
  citations: Citation[];
}

export interface LineDecision {
  line_number: number;
  decision: Decision;
  carc?: string | null;
  rarc?: string | null;
  reason: string;
}

export interface Recommendation {
  claim_id: string;
  decision: Decision;
  confidence: number;
  all_checks_passed: boolean;
  checks: { validation: boolean; eligibility: boolean; clinical: boolean };
  line_decisions: LineDecision[];
  findings: Finding[];
  summary: string;
  headline?: string;
  key_points?: string[];
  verify_before_payment?: string[];
  rationale: string;
  models: Record<string, string>;
}

export interface ServiceLine {
  line_number: number;
  service_start_date: string | null;
  place_of_service: string | null;
  procedure_code: string | null;
  modifiers: string | null;
  diagnosis_pointer: string | null;
  units: number | null;
  charge_amount: number | null;
}

export interface Extraction {
  document_class: string;
  page_indices: string;
  field_name: string;
  field_value: string | null;
  confidence: number | null;
}

export interface ClaimDocument {
  part_id: number | null;
  document_id: number;
  /** PACK = whole multi-document file (parent row), PART = a document BDA found, FILE = not yet read. */
  kind: "PACK" | "PART" | "FILE";
  name: string;
  document_class: string | null;
  declared_type: string;
  page_start: number | null;
  page_end: number | null;
  source_file_name: string;
  origin: "INITIAL" | "ADDITIONAL";
  status: "PROCESSING" | "READY" | "FAILED";
  added_at: string;
}

export interface DocumentBatch {
  batch_id: string;
  stage: string;
  document_count: number;
  created_at: string;
  updated_at: string;
}

export interface ReviewRun {
  run_id: number;
  mode: string;
  requested_by: string | null;
  requested_at: string;
  reason: string | null;
  outcome: string;
  agent_decision: string | null;
  agent_confidence: string | number | null;
  final_decision: string | null;
}
