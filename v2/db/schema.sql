-- Agentic claims (v2) schema. Statements are separated by ';' and executed one by one via the RDS Data API,
-- so do not use ';' inside string literals or function bodies.

CREATE TABLE IF NOT EXISTS plans (
    plan_id            SERIAL PRIMARY KEY,
    plan_name          VARCHAR(100) NOT NULL UNIQUE,
    eoc_document_key   VARCHAR(500),
    deductible         NUMERIC(10,2) NOT NULL DEFAULT 0,
    coinsurance_pct    NUMERIC(5,2) NOT NULL DEFAULT 0,
    auto_approve_limit NUMERIC(10,2) NOT NULL DEFAULT 1000
);

CREATE TABLE IF NOT EXISTS members (
    member_id        SERIAL PRIMARY KEY,
    insured_id_number VARCHAR(50) NOT NULL UNIQUE,
    insured_name     VARCHAR(200) NOT NULL,
    birth_date       DATE,
    group_number     VARCHAR(50),
    plan_id          INTEGER NOT NULL REFERENCES plans(plan_id),
    coverage_start   DATE NOT NULL,
    coverage_end     DATE,
    phone_number     VARCHAR(50),
    address          VARCHAR(300)
);

CREATE TABLE IF NOT EXISTS patients (
    patient_id              SERIAL PRIMARY KEY,
    member_id               INTEGER NOT NULL REFERENCES members(member_id),
    first_name              VARCHAR(100) NOT NULL,
    last_name               VARCHAR(100) NOT NULL,
    birth_date              DATE,
    sex                     VARCHAR(10),
    relationship_to_insured VARCHAR(30)
);

CREATE TABLE IF NOT EXISTS other_coverage (
    other_coverage_id SERIAL PRIMARY KEY,
    member_id         INTEGER NOT NULL REFERENCES members(member_id),
    payer_name        VARCHAR(200) NOT NULL,
    policy_number     VARCHAR(50),
    is_primary        BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS providers (
    provider_id  VARCHAR(50) PRIMARY KEY,
    npi          VARCHAR(10) NOT NULL UNIQUE,
    name         VARCHAR(200) NOT NULL,
    tax_id       VARCHAR(20),
    in_network   BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS claims (
    claim_id            VARCHAR(40) PRIMARY KEY,
    provider_id         VARCHAR(50) NOT NULL REFERENCES providers(provider_id),
    submitted_by        VARCHAR(100) NOT NULL,
    status              VARCHAR(30) NOT NULL DEFAULT 'DRAFT',
    member_id           INTEGER REFERENCES members(member_id),
    patient_name        VARCHAR(200),
    insured_id_number   VARCHAR(50),
    total_charges       NUMERIC(12,2),
    execution_arn       VARCHAR(500),
    bda_task_token      TEXT,
    review_task_token   TEXT,
    agent_decision      VARCHAR(20),
    agent_confidence    NUMERIC(4,3),
    final_decision      VARCHAR(20),
    failure_reason      TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_claims_provider ON claims(provider_id);
CREATE INDEX IF NOT EXISTS idx_claims_status ON claims(status);

CREATE TABLE IF NOT EXISTS claim_documents (
    document_id   SERIAL PRIMARY KEY,
    claim_id      VARCHAR(40) NOT NULL REFERENCES claims(claim_id),
    s3_key        VARCHAR(600) NOT NULL,
    file_name     VARCHAR(300) NOT NULL,
    content_type  VARCHAR(100) NOT NULL,
    declared_type VARCHAR(50) NOT NULL,
    detected_type VARCHAR(100),
    bda_invocation_arn VARCHAR(500),
    bda_status    VARCHAR(30),
    bda_output_prefix VARCHAR(600),
    uploaded_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (claim_id, s3_key)
);

ALTER TABLE claim_documents ADD COLUMN IF NOT EXISTS origin VARCHAR(12) NOT NULL DEFAULT 'INITIAL';
ALTER TABLE claim_documents ADD COLUMN IF NOT EXISTS batch_id VARCHAR(40);
ALTER TABLE claim_documents ADD COLUMN IF NOT EXISTS page_count INTEGER;
ALTER TABLE claim_documents ADD COLUMN IF NOT EXISTS segment_count INTEGER;
CREATE TABLE IF NOT EXISTS document_batches (
    batch_id     VARCHAR(40) PRIMARY KEY,
    claim_id     VARCHAR(40) NOT NULL REFERENCES claims(claim_id),
    requested_by VARCHAR(100),
    stage        VARCHAR(30) NOT NULL DEFAULT 'UPLOADING',
    task_token   TEXT,
    execution_arn VARCHAR(300),
    reopened     BOOLEAN NOT NULL DEFAULT FALSE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_document_batches_claim ON document_batches(claim_id);
CREATE TABLE IF NOT EXISTS claim_document_parts (
    part_id      SERIAL PRIMARY KEY,
    claim_id     VARCHAR(40) NOT NULL REFERENCES claims(claim_id),
    document_id  INTEGER NOT NULL REFERENCES claim_documents(document_id),
    batch_id     VARCHAR(40),
    segment_index INTEGER NOT NULL,
    document_class VARCHAR(100),
    display_name VARCHAR(300),
    page_start   INTEGER,
    page_end     INTEGER,
    page_indices VARCHAR(200),
    blueprint_confidence NUMERIC(4,3),
    s3_bucket_kind VARCHAR(10) NOT NULL,
    s3_key       VARCHAR(600) NOT NULL,
    is_original  BOOLEAN NOT NULL DEFAULT TRUE,
    content_type VARCHAR(100),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (document_id, segment_index)
);
CREATE INDEX IF NOT EXISTS idx_claim_document_parts_claim ON claim_document_parts(claim_id);
CREATE TABLE IF NOT EXISTS service_lines (
    line_id            SERIAL PRIMARY KEY,
    claim_id           VARCHAR(40) NOT NULL REFERENCES claims(claim_id),
    line_number        INTEGER NOT NULL,
    service_start_date DATE,
    service_end_date   DATE,
    place_of_service   VARCHAR(10),
    procedure_code     VARCHAR(10),
    modifiers          VARCHAR(20),
    diagnosis_pointer  VARCHAR(10),
    units              NUMERIC(8,2),
    charge_amount      NUMERIC(12,2),
    rendering_npi      VARCHAR(10),
    UNIQUE (claim_id, line_number)
);

CREATE TABLE IF NOT EXISTS extractions (
    extraction_id  SERIAL PRIMARY KEY,
    claim_id       VARCHAR(40) NOT NULL REFERENCES claims(claim_id),
    document_id    INTEGER REFERENCES claim_documents(document_id),
    document_class VARCHAR(100) NOT NULL,
    source_key     VARCHAR(600),
    page_indices   VARCHAR(100),
    field_name     VARCHAR(200) NOT NULL,
    field_value    TEXT,
    confidence     NUMERIC(4,3)
);

CREATE INDEX IF NOT EXISTS idx_extractions_claim ON extractions(claim_id);

CREATE TABLE IF NOT EXISTS agent_runs (
    run_id          SERIAL PRIMARY KEY,
    claim_id        VARCHAR(40) NOT NULL REFERENCES claims(claim_id),
    session_id      VARCHAR(100) NOT NULL,
    prompt_version  VARCHAR(20),
    models          VARCHAR(500),
    recommendation  JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS decisions (
    decision_id  SERIAL PRIMARY KEY,
    claim_id     VARCHAR(40) NOT NULL REFERENCES claims(claim_id),
    decided_by   VARCHAR(20) NOT NULL,
    actor        VARCHAR(100) NOT NULL,
    decision     VARCHAR(20) NOT NULL,
    line_decisions JSONB,
    reason       TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Re-run support (Mode A). claims.current_run is the claim-scoped run number (1 = original submission).
-- agent_runs.run_id stays the global row id; claim_run_id is the per-claim run it belongs to.
ALTER TABLE claims ADD COLUMN IF NOT EXISTS current_run INTEGER NOT NULL DEFAULT 1;
ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS claim_run_id INTEGER NOT NULL DEFAULT 1;
ALTER TABLE decisions ADD COLUMN IF NOT EXISTS claim_run_id INTEGER NOT NULL DEFAULT 1;
-- Extraction run that produced the row. Mode A never changes it. Reserved for a later re-extraction mode.
ALTER TABLE claim_document_parts ADD COLUMN IF NOT EXISTS run_id INTEGER NOT NULL DEFAULT 1;
ALTER TABLE extractions ADD COLUMN IF NOT EXISTS run_id INTEGER NOT NULL DEFAULT 1;
CREATE TABLE IF NOT EXISTS claim_runs (
    claim_id           VARCHAR(40) NOT NULL REFERENCES claims(claim_id),
    run_id             INTEGER NOT NULL,
    mode               VARCHAR(20) NOT NULL,
    reason             TEXT,
    requested_by       VARCHAR(100) NOT NULL,
    requested_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    prior_status       VARCHAR(30),
    prior_failure_reason TEXT,
    prior_execution_arn  VARCHAR(500),
    execution_arn      VARCHAR(500),
    case_key           VARCHAR(600),
    status             VARCHAR(20) NOT NULL DEFAULT 'STARTED',
    PRIMARY KEY (claim_id, run_id)
);
CREATE INDEX IF NOT EXISTS idx_claim_runs_claim ON claim_runs(claim_id);
CREATE TABLE IF NOT EXISTS audit_events (
    event_id   SERIAL PRIMARY KEY,
    claim_id   VARCHAR(40) NOT NULL,
    actor      VARCHAR(100) NOT NULL,
    event_type VARCHAR(50) NOT NULL,
    detail     JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ref_icd10 (
    code        VARCHAR(10) PRIMARY KEY,
    description VARCHAR(300) NOT NULL
);

CREATE TABLE IF NOT EXISTS ref_procedure (
    code        VARCHAR(10) PRIMARY KEY,
    code_system VARCHAR(10) NOT NULL,
    description VARCHAR(300) NOT NULL,
    max_units_per_day NUMERIC(8,2)
);

CREATE TABLE IF NOT EXISTS ref_pos (
    code        VARCHAR(4) PRIMARY KEY,
    description VARCHAR(200) NOT NULL
);

CREATE TABLE IF NOT EXISTS ref_modifier (
    code        VARCHAR(4) PRIMARY KEY,
    description VARCHAR(200) NOT NULL
)
