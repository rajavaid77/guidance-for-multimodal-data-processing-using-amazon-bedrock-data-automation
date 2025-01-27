
INSERT INTO INSURED_PERSON (insured_name, insured_policy_number, insured_plan_name, insured_birth_date, insured_group_number, phone_number, address)
VALUES
('Jane Doe', '11-2234-10190', 'AnyHealth Plus', '1965-06-12', 'G4683A', '858 555 0100', '123 Any Street, Any City, CA 92127'),
('Ana Carolina Silva', '12-1134-90110', 'AnyHealth Premium', '1992-06-15', 'G5794A', '555 555 0192', '100 Main Street, Anytown, USA'),
('Mateo Jackson', '90-1234-11012', 'AnyHealth Standard', '1985-11-03', 'G6905B', '555 555 0194', '404 Anywhere Street, Nowhere Town, USA'),


INSERT INTO PATIENT (insured_id, patient_firstname, patient_lastname, patient_birth_date, relationship_to_insured, phone_number, sex, address)
VALUES
(1, 'John', 'Doe', '1960-10-10', 'Spouse', '858 555 0100', 'M', '123 Any Street, Any City, CA 92127'),
(2, 'Ana', 'Carolina Silva', '1992-06-15', 'Self', '555 555 0192', 'M', '100 Main Street, Anytown, USA'),
(3, 'Mateo', 'Jackson', '1985-11-03', 'Self', '555 555 0194', 'N', '404 Anywhere Street, Nowhere Town, USA'),
