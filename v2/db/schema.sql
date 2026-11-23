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
