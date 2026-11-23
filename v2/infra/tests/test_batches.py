import pytest

from tests.fakes import FakeDb, install
from workflow import batch_gate, mark_batch_failed, merge_batch, start_batch_bda

BATCH = "BATCH-" + "a" * 32
EVENT = {"claim_id": "CLM-1", "batch_id": BATCH}


def calls_matching(fake, text):
    return [c for c in fake.calls if text in " ".join(c[0].split())]


def test_start_batch_key_must_match_layout():
    assert start_batch_bda.parse_key(f"batches/CLM-1/{BATCH}/submit.json") == ("CLM-1", BATCH)
    for bad in ("claims/CLM-1/submit.json", "batches/CLM-1/nope/submit.json", f"batches/CLM-1/{BATCH}/x.json"):
        with pytest.raises(ValueError):
            start_batch_bda.parse_key(bad)


def test_gate_opens_when_claim_is_idle(monkeypatch):
    fake = FakeDb(updated={"SET stage = 'MERGING'": 1})
    install(monkeypatch, batch_gate, fake)
    assert batch_gate.handler(EVENT, None) == {"ready": True}
    sql = " ".join(calls_matching(fake, "MERGING")[0][0].split())
    # Blocks while the main flow is active or another batch is merging/reviewing.
    for status in ("EXTRACTING", "AGENT_REVIEW"):
        assert status in sql
    assert "o.stage IN ('MERGING', 'AGENT_REVIEW')" in sql
    assert "PENDING_REVIEW" not in sql


def test_gate_waits_while_claim_or_other_batch_is_busy(monkeypatch):
    fake = FakeDb(
        updated={"SET stage = 'MERGING'": 0},
        responses={"SELECT stage FROM document_batches": [{"stage": "EXTRACTING"}]},
    )
    install(monkeypatch, batch_gate, fake)
    assert batch_gate.handler(EVENT, None) == {"ready": False}
    assert calls_matching(fake, "SET stage = 'WAITING'")


def test_gate_is_idempotent_for_a_batch_already_merging(monkeypatch):
    fake = FakeDb(
        updated={"SET stage = 'MERGING'": 0}, responses={"SELECT stage FROM document_batches": [{"stage": "MERGING"}]}
    )
    install(monkeypatch, batch_gate, fake)
    assert batch_gate.handler(EVENT, None) == {"ready": True}


class FakeS3:
    def __init__(self, case):
        import json

        self.body = json.dumps(case).encode()
        self.put = None

    def get_object(self, Bucket, Key):
        import io

        return {"Body": io.BytesIO(self.body)}

    def put_object(self, **kwargs):
        self.put = kwargs


def run_merge(monkeypatch, *, reopened, status, evidence=None):
    import json

    case = {
        "cms1500": {"patient_name": {"value": "X"}},
        "service_lines": [{"line_number": 1}],
        "evidence": evidence or [],
    }
    fake = FakeDb(
        responses={
            "FROM claim_documents WHERE claim_id": [
                {"document_id": 7, "claim_id": "CLM-1", "s3_key": "claims/CLM-1/docs/b1-01-a.pdf"}
            ],
            "SELECT status FROM claims": [{"status": status}],
        },
        updated={"WHERE claim_id = :c AND status = 'PENDED_INFO_REQUESTED'": 1 if reopened else 0},
    )
    install(monkeypatch, merge_batch, fake)
    fake_s3 = FakeS3(case)
    monkeypatch.setattr(merge_batch, "s3", fake_s3)
    monkeypatch.setenv("BDA_OUTPUT_BUCKET", "out")
    monkeypatch.setenv("INTAKE_BUCKET", "intake")
    segment = {
        "document_class": "LAB_REPORT",
        "source_key": "claims/CLM-1/docs/b1-01-a.pdf",
        "page_indices": [1],
        "inference": {"results": [1]},
        "fields": {"test": {"value": "A1C", "confidence": 0.9}},
        "doc": {"document_id": 7},
    }
    monkeypatch.setattr(merge_batch, "_segments_for", lambda doc, out, intake: [segment])
    result = merge_batch.handler(EVENT, None)
    return result, fake, json.loads(fake_s3.put["Body"])


def test_merge_pended_claim_reopens_once_and_appends_evidence(monkeypatch):
    result, fake, case = run_merge(monkeypatch, reopened=True, status="AGENT_REVIEW")
    assert result["action"] == "REOPEN"
    reopen = calls_matching(fake, "SET status = 'AGENT_REVIEW', final_decision = NULL")
    assert len(reopen) == 1 and "WHERE claim_id = :c AND status = 'PENDED_INFO_REQUESTED'" in " ".join(
        reopen[0][0].split()
    )
    assert calls_matching(fake, "SET reopened = TRUE")
    # Claim form and service lines are untouched; evidence is appended.
    assert case["cms1500"] == {"patient_name": {"value": "X"}} and case["service_lines"] == [{"line_number": 1}]
    assert [e["document_class"] for e in case["evidence"]] == ["LAB_REPORT"]
    assert calls_matching(fake, "SET stage = 'AGENT_REVIEW'")


def test_merge_under_review_keeps_status_and_token(monkeypatch):
    result, fake, _ = run_merge(monkeypatch, reopened=False, status="PENDING_REVIEW")
    assert result["action"] == "REVIEW_IN_PLACE"
    assert not calls_matching(fake, "SET reopened")
    assert not calls_matching(fake, "review_task_token")
    assert len(calls_matching(fake, "UPDATE claims")) == 1  # only the guarded reopen attempt, which matched no row


@pytest.mark.parametrize("status", ["APPROVED", "DENIED", "FAILED"])
def test_merge_finalized_claim_records_only(monkeypatch, status):
    result, fake, case = run_merge(monkeypatch, reopened=False, status=status)
    assert result["action"] == "RECORD_ONLY"
    assert not calls_matching(fake, "SET stage = 'AGENT_REVIEW'")
    assert any(c[0] == "AUDIT" and "DOCUMENTS_ADDED_AFTER_DECISION" in c[1]["args"] for c in fake.calls)
    assert len(case["evidence"]) == 1


def test_merge_replaces_earlier_attempt_evidence(monkeypatch):
    old = [
        {"document_class": "LAB_REPORT", "source_key": "claims/CLM-1/docs/b1-01-a.pdf"},
        {"document_class": "X", "source_key": "k"},
    ]
    _, _, case = run_merge(monkeypatch, reopened=False, status="PENDING_REVIEW", evidence=old)
    assert [e["source_key"] for e in case["evidence"]] == ["k", "claims/CLM-1/docs/b1-01-a.pdf"]


def test_merge_rejects_busy_claim(monkeypatch):
    with pytest.raises(RuntimeError):
        run_merge(monkeypatch, reopened=False, status="AGENT_REVIEW")


ERROR = {"Error": "States.TaskFailed", "Cause": '{"errorMessage": "boom"}'}


def test_failure_marks_batch_only_when_not_reopened(monkeypatch):
    fake = FakeDb(responses={"RETURNING reopened": [{"reopened": False}]})
    install(monkeypatch, mark_batch_failed, fake)
    result = mark_batch_failed.handler(EVENT | {"error": ERROR}, None)
    assert result["stage"] == "FAILED" and result["claim_failed"] is False
    assert calls_matching(fake, "UPDATE document_batches SET stage = 'FAILED'")
    assert not calls_matching(fake, "UPDATE claims SET status = 'FAILED'")


def test_failure_fails_claim_when_batch_reopened_it(monkeypatch):
    fake = FakeDb(responses={"RETURNING reopened": [{"reopened": True}]})
    install(monkeypatch, mark_batch_failed, fake)
    result = mark_batch_failed.handler(EVENT | {"error": ERROR}, None)
    assert result["claim_failed"] is True
    assert calls_matching(fake, "UPDATE claims SET status = 'FAILED'")
