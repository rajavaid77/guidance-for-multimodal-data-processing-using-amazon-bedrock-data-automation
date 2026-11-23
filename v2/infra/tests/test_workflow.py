import io
import json

import pytest
from pypdf import PdfReader, PdfWriter

from tests.fakes import FakeDb, install
from workflow import assemble_case, bda_callback, parts
from workflow.bda_output import build_case, classify, parse_segments, part_name, segment_record, standard_pages
from workflow.routing import route


def custom_output(blueprint, inference, explain=None, pages=(0,)):
    return {
        "matched_blueprint": {"name": blueprint, "confidence": 0.97},
        "inference_result": inference,
        "explainability_info": [explain or {}],
        "split_document": {"page_indices": list(pages)},
    }


FORM = {
    "insured_id_number": "11-2234-10190",
    "patient_name": "Doe, John",
    "patient_date_of_birth": "1960-10-10",
    "total_charges": 660.0,
    "billing_provider_npi": "1234567890",
    "diagnosis_1": "M54.9",
    "medical_procedures": [
        {"service_start_date": "2005-11-04", "procedure_code": "97810", "charge_amount": 170.0, "diagnosis_code": "A"},
        {"procedure_code": None, "charge_amount": None},
    ],
}
FORM["insurance_program"] = "GROUP_HEALTH_PLAN"
FORM["another_health_benefit_plan_indicator"] = "NO"
EXPLAIN = {k: {"confidence": 0.95} for k in FORM if k != "medical_procedures"} | {"diagnosis_1": {"confidence": 0.5}}


def test_classify_by_blueprint_suffix():
    assert classify("agentic-claims-cms1500") == "CMS1500"
    assert classify("agentic-claims-medical-record") == "MEDICAL_RECORD"
    assert classify("agentic-claims-discharge-summary") == "DISCHARGE_SUMMARY"
    assert classify(None) == "OTHER"


def test_classify_aws_managed_blueprints():
    assert classify("bedrock-data-automation-public-us-medical-insurance-card") == "INSURANCE_CARD"
    assert classify("US-Medical-Insurance-Card") == "INSURANCE_CARD"
    assert classify("bedrock-data-automation-public-prescription-label") == "PRESCRIPTION_LABEL"
    assert classify("bedrock_data_automation_public_us_driver_license") == "DRIVER_LICENSE"
    assert classify("bedrock-data-automation-public-invoice") == "INVOICE"
    assert classify("bedrock-data-automation-public-bank-statement") == "OTHER"


def test_build_case_from_segments():
    form = segment_record(custom_output("p-cms1500", FORM, EXPLAIN), "claims/c/docs/01-form.pdf")
    note = segment_record(
        custom_output(
            "p-medical-record", {"encounter_date": "2005-11-04", "diagnoses": [{"code": "M54.9"}]}, pages=(0, 1)
        ),
        "claims/c/docs/02-note.pdf",
    )
    case = build_case("CLM-x", {"provider_id": "P", "npi": "1", "name": "n"}, [form, note], 0.8)
    assert case["cms1500"]["insured_id_number"]["value"] == "11-2234-10190"
    assert [line["procedure_code"] for line in case["service_lines"]] == ["97810"]  # empty line dropped
    assert case["low_confidence_fields"] == ["diagnosis_1"]  # optional checkbox items absent -> not flagged
    assert case["evidence"][0]["page_indices"] == [1, 2]
    assert case["evidence"][0]["fields"]["diagnoses"]["value"] == [{"code": "M54.9"}]


def blank_form_fields():
    """What BDA returns when an invoice is matched to the CMS-1500 blueprint: every field present, almost all empty."""
    return {
        "patient_name": "",
        "physician_signature_present": "",
        "physician_signed_date": "",
        "total_charges": 335,
        "medical_procedures": [{"procedure_code": "99214", "charge_amount": 185}],
    }


def test_build_case_ignores_invoice_matched_to_the_cms1500_blueprint():
    """Regression: an invoice scored 0.70 on the CMS-1500 blueprint and the agents read its blank item 31."""
    real = segment_record(custom_output("p-cms1500", FORM | {"physician_signature_present": "YES"}), "k1")
    invoice = segment_record(custom_output("p-cms1500", blank_form_fields(), pages=(9,)), "k1")
    invoice["blueprint_confidence"] = 0.70
    case = build_case("CLM-x", {"provider_id": "P", "npi": "1", "name": "n"}, [invoice, real], 0.8)
    assert case["cms1500"]["physician_signature_present"]["value"] == "YES"
    assert [e["document_class"] for e in case["evidence"]] == ["OTHER"]
    assert case["evidence"][0]["fields"] == {}  # the empty form fields are not passed on
    assert [line["procedure_code"] for line in case["service_lines"]] == ["97810"]


def test_build_case_prefers_the_form_with_more_filled_fields_over_a_longer_empty_one():
    thin = segment_record(custom_output("p-cms1500", {"patient_name": "Doe", "total_charges": 1}), "k")
    full = segment_record(custom_output("p-cms1500", FORM, EXPLAIN), "k")
    thin["fields"] = {f"f{i}": {"value": "", "confidence": None} for i in range(80)} | thin["fields"]
    case = build_case("CLM-x", {}, [thin, full], 0.8)
    assert case["cms1500"]["insured_id_number"]["value"] == "11-2234-10190"


def test_parse_segments_keeps_one_cms1500_per_file():
    a = matched(0, "p-cms1500", (0,))
    b = matched(1, "p-cms1500", (9,))
    b[1]["matched_blueprint"]["confidence"] = 0.70
    c = matched(2, "p-lab-report", (4,))
    segs = parse_segments(job_metadata(a[0], c[0], b[0]), "0", loader_for(a, b, c))
    assert [s["document_class"] for s in segs] == ["CMS1500", "LAB_REPORT", "OTHER"]


def test_segments_for_demotes_the_weaker_cms1500_match_before_it_reaches_the_case(monkeypatch):
    form = custom_output("p-cms1500", FORM | {"physician_signature_present": "YES"}, pages=(0,))
    invoice = custom_output("p-cms1500", blank_form_fields(), pages=(1,))
    invoice["matched_blueprint"]["confidence"] = 0.70
    metadata = job_metadata(
        {"custom_output_path": "s3://o/0.json", "custom_output_status": "MATCH"},
        {"custom_output_path": "s3://o/1.json", "custom_output_status": "MATCH"},
    )
    store = {"s3://o/0.json": form, "s3://o/1.json": invoice}
    monkeypatch.setattr(assemble_case, "_read_json", lambda a, b=None: metadata if b else store[a])
    seen = {}
    monkeypatch.setattr(assemble_case, "record_parts", lambda cid, doc, parsed, *a: seen.update(parsed=parsed))
    doc = {"claim_id": "CLM-x", "s3_key": "k", "bda_output_prefix": "claims/c/1/uuid/0"}
    records = assemble_case._segments_for(doc, "bucket", "intake")
    assert [r["document_class"] for r in records] == ["CMS1500", "OTHER"]
    assert records[1]["fields"] == {} and records[1]["inference"] == {}
    assert [p["document_class"] for p in seen["parsed"]] == ["CMS1500", "OTHER"]  # the parts list agrees


def test_parse_segments_single_cms1500_is_untouched():
    a = matched(0, "p-cms1500", (0,))
    a[1]["matched_blueprint"]["confidence"] = 0.51
    assert parse_segments(job_metadata(a[0]), "0", loader_for(a))[0]["document_class"] == "CMS1500"


def test_build_case_requires_claim_form():
    note = segment_record(custom_output("p-medical-record", {}), "k")
    with pytest.raises(ValueError, match="NoClaimForm"):
        build_case("CLM-x", {}, [note], 0.8)


@pytest.mark.parametrize(
    "rec,total,expected",
    [
        ({"decision": "APPROVE", "all_checks_passed": True, "confidence": 0.95}, 500, "AUTO"),
        ({"decision": "APPROVE", "all_checks_passed": True, "confidence": 0.95}, 5000, "REVIEW"),
        ({"decision": "APPROVE", "all_checks_passed": True, "confidence": 0.7}, 100, "REVIEW"),
        ({"decision": "APPROVE", "all_checks_passed": False, "confidence": 0.99}, 100, "REVIEW"),
        ({"decision": "DENY", "all_checks_passed": True, "confidence": 0.99}, 100, "REVIEW"),
        ({"decision": "APPROVE", "all_checks_passed": True, "confidence": 0.99}, None, "REVIEW"),
    ],
)
def test_routing_never_auto_denies(rec, total, expected):
    assert route(rec, total, 1000, 0.9, 1500)[0] == expected


def job_metadata(*segments, asset_id="0"):
    return {"output_metadata": [{"asset_id": asset_id, "segment_metadata": list(segments)}]}


def matched(index, name, pages):
    return (
        {"segment_index": index, "custom_output_path": f"s3://o/{index}.json", "custom_output_status": "MATCH"},
        custom_output(name, {}, pages=pages),
    )


def loader_for(*pairs):
    docs = {seg["custom_output_path"]: out for seg, out in pairs if seg.get("custom_output_path")}
    return lambda path: docs[path]


def test_parse_segments_single():
    pair = matched(0, "p-cms1500", (0,))
    segs = parse_segments(job_metadata(pair[0]), "0", loader_for(pair))
    assert [(s["segment_index"], s["document_class"], s["page_indices"]) for s in segs] == [(0, "CMS1500", [1])]


def test_parse_segments_pack_with_non_contiguous_pages():
    pairs = [matched(0, "p-cms1500", (0, 1)), matched(1, "p-lab-report", (2, 4)), matched(2, "p-medical-record", (3,))]
    segs = parse_segments(job_metadata(*[p[0] for p in pairs]), "0", loader_for(*pairs))
    assert [s["page_indices"] for s in segs] == [[1, 2], [3, 5], [4]]
    assert [s["document_class"] for s in segs] == ["CMS1500", "LAB_REPORT", "MEDICAL_RECORD"]
    assert part_name("pack.pdf", "LAB_REPORT", [3, 5], True) == "Lab report (pages 3-5)"
    assert part_name("pack.pdf", "OTHER", [], False) == "pack.pdf"


def test_parse_segments_unmatched_becomes_other():
    pair = matched(0, "p-cms1500", (0,))
    unmatched = {"segment_index": 1, "custom_output_status": "NO_MATCH"}
    segs = parse_segments(job_metadata(pair[0], unmatched), "0", loader_for(pair))
    assert (
        segs[1]["document_class"] == "OTHER" and segs[1]["page_indices"] == [] and segs[1]["custom_output_path"] is None
    )


def standard(start, end):
    """Shape of a real BDA standard_output/N/result.json (metadata range is 0-based and inclusive)."""
    return {
        "metadata": {"start_page_index": start, "end_page_index": end, "number_of_pages": end - start + 1},
        "pages": [],
    }


def test_parse_segments_unmatched_pages_come_from_standard_output():
    """Real job_metadata.json has no segment_index; position is the index. Unmatched segments still have pages."""
    pair = matched(0, "p-cms1500", (0, 1))
    first = {
        "custom_output_path": "s3://o/0.json",
        "custom_output_status": "MATCH",
        "standard_output_path": "s3://s/0.json",
    }
    no_match = [
        {"custom_output_status": "NO_MATCH", "standard_output_path": "s3://s/1.json"},
        {"custom_output_status": "NO_MATCH", "standard_output_path": "s3://s/2.json"},
    ]
    store = {
        pair[0]["custom_output_path"]: pair[1],
        "s3://s/0.json": standard(0, 1),
        "s3://s/1.json": standard(2, 2),
        "s3://s/2.json": standard(3, 5),
    }
    segs = parse_segments(job_metadata(first, *no_match), "0", store.__getitem__)
    assert [(s["segment_index"], s["document_class"], s["page_indices"]) for s in segs] == [
        (0, "CMS1500", [1, 2]),
        (1, "OTHER", [3]),
        (2, "OTHER", [4, 5, 6]),
    ]


def test_parse_segments_matched_without_split_document_uses_standard_output():
    seg = {
        "custom_output_path": "s3://o/0.json",
        "custom_output_status": "MATCH",
        "standard_output_path": "s3://s/0.json",
    }
    store = {
        "s3://o/0.json": {"matched_blueprint": {"name": "p-lab-report", "confidence": 0.9}},
        "s3://s/0.json": standard(4, 4),
    }
    segs = parse_segments(job_metadata(seg), "0", store.__getitem__)
    assert segs[0]["page_indices"] == [5] and segs[0]["document_class"] == "LAB_REPORT"


def test_standard_pages_fallback_to_pages_list():
    assert standard_pages({"metadata": {}, "pages": [{"page_index": 2}, {"page_index": 3}]}) == [3, 4]
    assert standard_pages({}) == []


def test_parse_segments_missing_split_document():
    seg = {"segment_index": 0, "custom_output_path": "s3://o/0.json", "custom_output_status": "MATCH"}
    out = {"matched_blueprint": {"name": "p-lab-report", "confidence": 0.9}, "inference_result": {}}
    segs = parse_segments(job_metadata(seg), "0", lambda _p: out)
    assert segs[0]["page_indices"] == [] and segs[0]["document_class"] == "LAB_REPORT"


def pdf_bytes(pages):
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=72, height=72)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


class FakeS3:
    def __init__(self, objects):
        self.objects = dict(objects)
        self.put = {}

    def get_object(self, Bucket, Key):
        return {"Body": io.BytesIO(self.objects[Key])}

    def put_object(self, Bucket, Key, Body, ContentType):
        self.put[Key] = (Bucket, Body, ContentType)


def seg(index, cls, pages):
    return {"segment_index": index, "document_class": cls, "page_indices": pages, "blueprint_confidence": 0.9}


DOC = {
    "document_id": 7,
    "s3_key": "claims/CLM-1/docs/01-pack.pdf",
    "file_name": "pack.pdf",
    "content_type": "application/pdf",
}


def inserted(fake):
    return [c[1]["rows"] for c in fake.calls if "INSERT INTO claim_document_parts" in c[0]][0]


def test_record_parts_splits_pack(monkeypatch):
    fake = FakeDb()
    install(monkeypatch, parts, fake)
    s3 = FakeS3({DOC["s3_key"]: pdf_bytes(5)})
    rows = parts.record_parts(
        "CLM-1",
        DOC,
        [seg(0, "CMS1500", [1, 2]), seg(1, "LAB_REPORT", [3, 5]), seg(2, "MEDICAL_RECORD", [4])],
        "out",
        "intake",
        s3,
    )
    assert sorted(s3.put) == [f"claims/CLM-1/parts/7/{i:03d}.pdf" for i in range(3)]
    assert len(PdfReader(io.BytesIO(s3.put["claims/CLM-1/parts/7/001.pdf"][1])).pages) == 2
    assert all(b == "out" and ct == "application/pdf" for b, _, ct in s3.put.values())
    assert [(r["ps"], r["pe"], r["kind"], r["orig"]) for r in inserted(fake)] == [
        (1, 5, "INTAKE", True),  # container row: the whole pack
        (1, 2, "OUTPUT", False),
        (3, 5, "OUTPUT", False),
        (4, 4, "OUTPUT", False),
    ]
    assert len(rows) == 4
    pack = inserted(fake)[0]
    assert pack["seg"] == -1 and pack["cls"] == "PACK" and pack["name"] == "pack.pdf" and pack["key"] == DOC["s3_key"]
    update = [c for c in fake.calls if "UPDATE claim_documents" in c[0]][0][1]
    assert update["t"] == "PACK" and update["n"] == 3 and update["pc"] == 5


def test_record_parts_falls_back_on_corrupt_pdf(monkeypatch):
    fake = FakeDb()
    install(monkeypatch, parts, fake)
    s3 = FakeS3({DOC["s3_key"]: b"not a pdf"})
    parts.record_parts("CLM-1", DOC, [seg(0, "CMS1500", [1]), seg(1, "LAB_REPORT", [2, 3])], "out", "intake", s3)
    assert not s3.put
    rows = inserted(fake)
    assert all(r["orig"] and r["kind"] == "INTAKE" and r["key"] == DOC["s3_key"] for r in rows)
    assert rows[0]["seg"] == -1 and rows[2]["ps"] == 2


def test_record_parts_single_part_reuses_original(monkeypatch):
    fake = FakeDb()
    install(monkeypatch, parts, fake)
    s3 = FakeS3({})
    parts.record_parts("CLM-1", DOC, [seg(0, "CMS1500", [1])], "out", "intake", s3)
    row = inserted(fake)[0]
    assert not s3.put and row["orig"] and row["key"] == DOC["s3_key"] and row["name"] == "pack.pdf"
    update = [c for c in fake.calls if "UPDATE claim_documents" in c[0]][0][1]
    assert update["t"] == "CMS1500" and update["n"] == 1


def callback_event(name):
    return {
        "detail-type": bda_callback.SUCCESS,
        "detail": {
            "job_status": "SUCCESS",
            "input_s3_object": {"s3_bucket": "intake", "name": name},
            "output_s3_location": {"name": "claims/CLM-1/7/abc/0"},
        },
    }


def test_initial_callback_ignores_running_batch_document(monkeypatch):
    fake = FakeDb(
        responses={
            "SELECT document_id, claim_id, batch_id": [{"document_id": 1, "claim_id": "CLM-1", "batch_id": None}],
            "count(*) AS n FROM claim_documents WHERE claim_id = :c AND bda_status = 'RUNNING'": lambda sql, p: [
                {"n": 0 if "batch_id IS NULL" in sql else 1}
            ],
            "count(*) AS n FROM claim_documents": [{"n": 0}],
            "UPDATE claims c SET bda_task_token": [{"bda_task_token": "main-token"}],
        }
    )
    install(monkeypatch, bda_callback, fake)
    sent = {}
    monkeypatch.setattr(bda_callback.sfn, "send_task_success", lambda **kw: sent.update(kw))
    result = bda_callback.handler(callback_event("claims/CLM-1/docs/01-a.pdf"), None)
    assert result["resumed"] and sent["taskToken"] == "main-token"
    assert json.loads(sent["output"]) == {"claim_id": "CLM-1"}
    assert not any("document_batches" in c[0] for c in fake.calls)


def test_batch_callback_uses_batch_token(monkeypatch):
    batch = "BATCH-" + "a" * 32
    fake = FakeDb(
        responses={
            "SELECT document_id, claim_id, batch_id": [{"document_id": 2, "claim_id": "CLM-1", "batch_id": batch}],
            "count(*) AS n FROM claim_documents": [{"n": 0}],
            "UPDATE document_batches d SET task_token": [{"task_token": "batch-token"}],
        }
    )
    install(monkeypatch, bda_callback, fake)
    sent = {}
    monkeypatch.setattr(bda_callback.sfn, "send_task_success", lambda **kw: sent.update(kw))
    result = bda_callback.handler(callback_event("claims/CLM-1/docs/b1-01-a.pdf"), None)
    assert result["resumed"] and sent["taskToken"] == "batch-token"
    assert json.loads(sent["output"]) == {"claim_id": "CLM-1", "batch_id": batch}
    assert not any("UPDATE claims c SET bda_task_token" in c[0] for c in fake.calls)
    assert all(c[1].get("b") == batch for c in fake.calls if "count(*)" in c[0])
