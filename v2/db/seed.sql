-- Demo seed data. Members align with the sample CMS-1500 forms in assets/data/claims_review/cms_1500 and the
-- Evidence of Coverage PDFs in assets/data/claims_review/eoc (uploaded to the policy bucket under eoc/).
-- Reference code sets are a SMALL demo subset, not a licensed code set.

INSERT INTO plans (plan_name, eoc_document_key, deductible, coinsurance_pct, auto_approve_limit) VALUES
('AnyHealth Plus', 'eoc/Evidence_of_Coverage_-_AnyHealth_Plus.pdf', 2500, 0, 1000),
('AnyHealth Premium', 'eoc/Evidence_of_Coverage_-_AnyHealth_Premium.pdf', 2000, 0, 1500),
('AnyHealth Standard', 'eoc/Evidence_of_Coverage_-_AnyHealth_Standard.pdf', 3000, 0, 750)
ON CONFLICT (plan_name) DO UPDATE SET deductible = EXCLUDED.deductible, coinsurance_pct = EXCLUDED.coinsurance_pct,
  auto_approve_limit = EXCLUDED.auto_approve_limit;

INSERT INTO members (insured_id_number, insured_name, birth_date, group_number, plan_id, coverage_start, coverage_end, phone_number, address)
SELECT v.insured_id_number, v.insured_name, v.birth_date::date, v.group_number, p.plan_id, v.coverage_start::date, v.coverage_end::date, v.phone_number, v.address
FROM (VALUES
  ('11-2234-10190', 'Jane Doe', '1965-06-12', 'G4683A', 'AnyHealth Plus', '2000-01-01', NULL, '858 555 0100', '123 Any Street, Any City, CA 92127'),
  ('12-1134-90110', 'Ana Carolina Silva', '1992-06-15', 'G5794A', 'AnyHealth Premium', '2000-01-01', NULL, '555 555 0192', '100 Main Street, Anytown, USA'),
  ('90-1234-11012', 'Mateo Jackson', '1985-11-03', 'G6905B', 'AnyHealth Standard', '2019-01-01', NULL, '555 555 0194', '404 Anywhere Street, Nowhere Town, USA'),
  ('123456789A', 'Joe Doe', '1965-06-03', 'A12345678', 'AnyHealth Premium', '2024-01-01', NULL, '206 555 0199', '123 Any Street, Any City, CA 11111')
) AS v(insured_id_number, insured_name, birth_date, group_number, plan_name, coverage_start, coverage_end, phone_number, address)
JOIN plans p ON p.plan_name = v.plan_name
ON CONFLICT (insured_id_number) DO UPDATE SET insured_name = EXCLUDED.insured_name, birth_date = EXCLUDED.birth_date,
  group_number = EXCLUDED.group_number, plan_id = EXCLUDED.plan_id, coverage_start = EXCLUDED.coverage_start,
  coverage_end = EXCLUDED.coverage_end, phone_number = EXCLUDED.phone_number, address = EXCLUDED.address;

INSERT INTO patients (member_id, first_name, last_name, birth_date, sex, relationship_to_insured)
SELECT m.member_id, v.first_name, v.last_name, v.birth_date::date, v.sex, v.rel
FROM (VALUES
  ('11-2234-10190', 'John', 'Doe', '1960-10-10', 'M', 'Spouse'),
  ('12-1134-90110', 'Ana', 'Silva', '1992-06-15', 'F', 'Self'),
  ('90-1234-11012', 'Mateo', 'Jackson', '1985-11-03', 'M', 'Self'),
  ('123456789A', 'Jane', 'Doe', '1967-02-14', 'F', 'Spouse')
) AS v(insured_id_number, first_name, last_name, birth_date, sex, rel)
JOIN members m ON m.insured_id_number = v.insured_id_number
WHERE NOT EXISTS (SELECT 1 FROM patients x WHERE x.member_id = m.member_id AND x.first_name = v.first_name AND x.last_name = v.last_name);

-- Demo providers. NPIs pass the CMS Luhn check digit (prefix 80840).
INSERT INTO providers (provider_id, npi, name, tax_id, in_network) VALUES
('PRV-1001', '1234567893', 'AnyCompany Medical Group', '12-3456789', TRUE),
('PRV-1002', '1245319599', 'Nowhere Town Cardiology', '45-6789012', TRUE)
ON CONFLICT (provider_id) DO UPDATE SET name = EXCLUDED.name, tax_id = EXCLUDED.tax_id;

INSERT INTO ref_icd10 (code, description) VALUES
('M54.9', 'Dorsalgia, unspecified'),
('M54.50', 'Low back pain, unspecified'),
('M25.552', 'Pain in left hip'),
('M25.551', 'Pain in right hip'),
('I20.9', 'Angina pectoris, unspecified'),
('R07.9', 'Chest pain, unspecified'),
('R07.89', 'Other chest pain'),
('I10', 'Essential (primary) hypertension'),
('E11.9', 'Type 2 diabetes mellitus without complications'),
('J06.9', 'Acute upper respiratory infection, unspecified'),
('Z00.00', 'Encounter for general adult medical examination without abnormal findings'),
('J44.9', 'Chronic obstructive pulmonary disease, unspecified'),
('J45.909', 'Unspecified asthma, uncomplicated'),
('E11.29', 'Type 2 diabetes mellitus with other diabetic kidney complication'),
('M54.5', 'Low back pain (retired code - use M54.50-M54.59 from FY2022)'),
('M54.2', 'Cervicalgia')
ON CONFLICT (code) DO NOTHING;

INSERT INTO ref_procedure (code, code_system, description, max_units_per_day) VALUES
('97810', 'CPT', 'Acupuncture, 1 or more needles, without electrical stimulation, initial 15 minutes', 1),
('73521', 'CPT', 'Radiologic examination, hips, bilateral, with pelvis, 2 views', 1),
('97124', 'CPT', 'Massage, each 15 minutes', 4),
('98940', 'CPT', 'Chiropractic manipulative treatment, spinal, 1-2 regions', 1),
('97110', 'CPT', 'Therapeutic exercise, each 15 minutes', 4),
('20610', 'CPT', 'Arthrocentesis, aspiration and/or injection, major joint', 2),
('77002', 'CPT', 'Fluoroscopic guidance for needle placement', 1),
('72100', 'CPT', 'Radiologic examination, spine, lumbosacral, 2 or 3 views', 1),
('93306', 'CPT', 'Echocardiography, transthoracic, complete, with Doppler', 1),
('93017', 'CPT', 'Cardiovascular stress test, tracing only', 1),
('93000', 'CPT', 'Electrocardiogram, routine, with interpretation and report', 1),
('99203', 'CPT', 'Office visit, new patient, low complexity', 1),
('99213', 'CPT', 'Office visit, established patient, low complexity', 1),
('99214', 'CPT', 'Office visit, established patient, moderate complexity', 1),
('94060', 'CPT', 'Bronchodilation responsiveness, spirometry pre- and post-bronchodilator', 1),
('94669', 'CPT', 'Mechanical chest wall oscillation to facilitate lung function, per session', 2),
('82043', 'CPT', 'Albumin, urine, microalbumin, quantitative', 2),
('99215', 'CPT', 'Office visit, established patient, high complexity', 1),
('A4223', 'HCPCS', 'Infusion supplies not used with external infusion pump, per cassette or bag', 4),
('A4649', 'HCPCS', 'Surgical supply, miscellaneous', 10)
ON CONFLICT (code) DO NOTHING;

INSERT INTO ref_pos (code, description) VALUES
('11', 'Office'), ('12', 'Home'), ('19', 'Off campus outpatient hospital'), ('21', 'Inpatient hospital'),
('22', 'On campus outpatient hospital'), ('23', 'Emergency room - hospital'), ('81', 'Independent laboratory'),
('02', 'Telehealth other than patient home'), ('10', 'Telehealth in patient home')
ON CONFLICT (code) DO NOTHING;

INSERT INTO ref_modifier (code, description) VALUES
('25', 'Significant, separately identifiable E/M service'), ('26', 'Professional component'),
('59', 'Distinct procedural service'), ('TC', 'Technical component'), ('LT', 'Left side'), ('RT', 'Right side'),
('GP', 'Services delivered under an outpatient physical therapy plan of care'),
('AT', 'Acute treatment (chiropractic)'), ('95', 'Synchronous telemedicine service via audio-video'),
('93', 'Synchronous telemedicine service via audio only'), ('76', 'Repeat procedure by same physician'),
('91', 'Repeat clinical diagnostic laboratory test'), ('GO', 'Outpatient occupational therapy plan of care'),
('50', 'Bilateral procedure')
ON CONFLICT (code) DO NOTHING
