"""Mode A re-run: guards, race handling, token neutralization, audit, and no deletion of extraction results."""

import json
import logging

import pytest
from botocore.exceptions import ClientError
from fakes import FakeDb, api_event, install

from api import examiner_reviews
from workflow import finalize, invoke_agent

CLAIM = "CLM-" + "a" * 32
REASON = "Prompt changed to fix MaxTokens; PHI: John Doe 1960"
UPDATE = "RETURNING c.current_run AS run_id"
OLD = {"run_id": 2, "old_status": "PENDING_REVIEW", "old_token": "old-tok", "old_arn": "arn:old", "old_failure": None}


def err(code):
    return ClientError({"Error": {"Code": code, "Message": "x"}}, "Op")


class FakeSfn:
    def __init__(self, stop_error=None, start_error=None):
        self.calls, self.stop_error, self.start_error = [], stop_error, start_error

    def stop_execution(self, **kw):
        self.calls.append(("stop", kw))
        if self.stop_error:
            raise self.stop_error

    def start_execution(self, **kw):
        self.calls.append(("start", kw))
        if self.start_error:
            raise self.start_error
        return {"executionArn": "arn:new"}


class FakeS3:
    def __init__(self, missing=False):
        self.missing = missing

    def head_object(self, **kw):
        if self.missing:
            raise err("404")
        return {}


def setup(monkeypatch, *, status="PENDING_REVIEW", final=None, batches=0, update=None, sfn=None, s3=None):
    monkeypatch.setenv("STATE_MACHINE_ARN", "arn:sm")
    monkeypatch.setenv("BDA_OUTPUT_BUCKET", "out")
    fake = FakeDb(
        {
            UPDATE: [update] if update else [],
            "SELECT status, final_decision FROM claims": [{"status": status, "final_decision": final}],
            "SELECT COUNT(*) AS n FROM document_batches": [{"n": batches}],
        }
    )
    install(monkeypatch, examiner_reviews, fake)
    monkeypatch.setattr(examiner_reviews, "sfn", sfn or FakeSfn())
    monkeypatch.setattr(examiner_reviews, "s3", s3 or FakeS3())
    return fake


def audit_events(fake):
    """(event_type, detail) of every audit row written through db.audit, in order."""
    return [(c[1]["args"][2], c[1]["args"][3]) for c in fake.calls if c[0] == "AUDIT"]


def call(body=None, groups="examiners", claim=CLAIM):
    body = {"mode": "AGENT", "reason": REASON} if body is None else body
    ev = api_event(
        "POST", "/reviews/{claimId}/rerun", groups=groups, provider_id=None, path={"claimId": claim}, body=body
    )
    return examiner_reviews.handler(ev, None)


def test_non_examiner_forbidden(monkeypatch):
    setup(monkeypatch)
    assert call(groups="providers")["statusCode"] == 403


def test_bad_claim_id_and_mode(monkeypatch):
    setup(monkeypatch)
    assert call(claim="CLM-../x")["statusCode"] == 404
    assert call({"mode": "BOGUS", "reason": REASON})["statusCode"] == 400
    res = call({"mode": "EXTRACTION", "reason": REASON})
    assert res["statusCode"] == 400 and "not supported" in json.loads(res["body"])["message"]


@pytest.mark.parametrize("reason", [None, "", "short", "x" * 1001, "   \x00\x01  ab  "])
def test_reason_required_with_bounds(monkeypatch, reason):
    fake = setup(monkeypatch, update=OLD)
    assert call({"mode": "AGENT", "reason": reason})["statusCode"] == 400
    assert not [c for c in fake.calls if UPDATE in c[0]]


@pytest.mark.parametrize(
    "status,final",
    [("APPROVED", "APPROVE"), ("DENIED", "DENY")],
)
def test_finalized_claim_rejected(monkeypatch, status, final):
    sfn = FakeSfn()
    fake = setup(monkeypatch, status=status, final=final, sfn=sfn)
    res = call()
    assert res["statusCode"] == 409 and "finalized" in json.loads(res["body"])["message"]
    assert sfn.calls == [] and not [c for c in fake.calls if UPDATE in c[0]]


def test_in_flight_batch_rejected(monkeypatch):
    sfn = FakeSfn()
    setup(monkeypatch, batches=1, sfn=sfn)
    res = call()
    assert res["statusCode"] == 409 and "Additional documents" in json.loads(res["body"])["message"]
    assert sfn.calls == []


def test_run_in_flight_rejected(monkeypatch):
    setup(monkeypatch, status="AGENT_REVIEW")
    assert call()["statusCode"] == 409


def test_guarded_update_requires_status_final_decision_and_batches(monkeypatch):
    fake = setup(monkeypatch, update=OLD)
    call()
    sql = " ".join(next(c[0] for c in fake.calls if UPDATE in c[0]).split())
    assert "status IN ('PENDING_REVIEW', 'FAILED') AND final_decision IS NULL" in sql
    assert "status = 'PENDED_INFO_REQUESTED' AND final_decision = 'PEND'" in sql
    assert "final_decision = NULL" in sql
    # APPROVE / DENY can never match the guard
    assert "'APPROVE'" not in sql and "'DENY'" not in sql
    assert "NOT EXISTS (SELECT 1 FROM document_batches" in sql and "FOR UPDATE" in sql
    assert "review_task_token = NULL" in sql and "current_run = c.current_run + 1" in sql


PENDED = {
    "run_id": 2,
    "old_status": "PENDED_INFO_REQUESTED",
    "old_token": None,
    "old_arn": "arn:done",
    "old_failure": None,
}


def test_pended_claim_can_be_rerun_without_stopping_anything(monkeypatch):
    sfn = FakeSfn()
    fake = setup(monkeypatch, status="PENDED_INFO_REQUESTED", final="PEND", update=PENDED, sfn=sfn)
    res = call()
    assert res["statusCode"] == 202 and json.loads(res["body"])["run_id"] == 2
    # the old execution already ended when the PEND was finalized: nothing to stop
    assert [c[0] for c in sfn.calls] == ["start"]
    assert audit_events(fake)[0] == (
        "RERUN_REQUESTED",
        {"run_id": 2, "mode": "AGENT", "prior_status": "PENDED_INFO_REQUESTED"},
    )
    assert next(c for c in fake.calls if "INSERT INTO claim_runs" in c[0])[1]["ps"] == "PENDED_INFO_REQUESTED"


def test_pended_claim_start_failure_goes_back_to_pended(monkeypatch):
    fake = setup(
        monkeypatch,
        status="PENDED_INFO_REQUESTED",
        final="PEND",
        update=PENDED,
        sfn=FakeSfn(start_error=err("StateMachineDoesNotExist")),
    )
    assert call()["statusCode"] == 502
    sqls = [" ".join(c[0].split()) for c in fake.calls]
    assert any("SET status = 'PENDED_INFO_REQUESTED', final_decision = 'PEND'" in q for q in sqls)
    assert not any("SET status = 'FAILED'" in q for q in sqls)
    assert any("status = 'START_FAILED'" in q for q in sqls)


def test_pended_claim_blocked_while_batch_in_flight(monkeypatch):
    sfn = FakeSfn()
    setup(monkeypatch, status="PENDED_INFO_REQUESTED", final="PEND", batches=1, sfn=sfn)
    assert call()["statusCode"] == 409 and sfn.calls == []


def test_missing_case_rejected(monkeypatch):
    sfn = FakeSfn()
    fake = setup(monkeypatch, update=OLD, sfn=sfn, s3=FakeS3(missing=True))
    res = call()
    assert res["statusCode"] == 409 and sfn.calls == []
    assert not [c for c in fake.calls if UPDATE in c[0]]


def test_success_from_pending_review_stops_old_then_starts_new(monkeypatch, caplog):
    sfn = FakeSfn()
    fake = setup(monkeypatch, update=OLD, sfn=sfn)
    with caplog.at_level(logging.DEBUG):
        res = call()
    assert res["statusCode"] == 202 and json.loads(res["body"])["run_id"] == 2
    assert [c[0] for c in sfn.calls] == ["stop", "start"]
    assert sfn.calls[0][1]["executionArn"] == "arn:old"
    start = sfn.calls[1][1]
    assert start["name"] == f"{CLAIM}-run2"
    payload = json.loads(start["input"])
    assert payload == {
        "entry": "AGENT",
        "claim_id": CLAIM,
        "run_id": 2,
        "case": {"case_key": f"claims/{CLAIM}/case.json"},
    }
    assert "John Doe" not in start["input"] and "John Doe" not in caplog.text
    # the old token is nulled in the same statement that starts the new run, and never stored again
    assert "old-tok" not in json.dumps([c[1] for c in fake.calls if "AUDIT" not in c[0]], default=str)


def test_audit_and_run_row_written_without_reason_in_audit(monkeypatch):
    fake = setup(monkeypatch, update=OLD)
    call()
    audits = [c[1]["args"] for c in fake.calls if c[0] == "AUDIT"]
    assert audits == [
        (CLAIM, "alice", "RERUN_REQUESTED", {"run_id": 2, "mode": "AGENT", "prior_status": "PENDING_REVIEW"})
    ]
    row = next(c for c in fake.calls if "INSERT INTO claim_runs" in c[0])[1]
    assert row["why"] == REASON and row["u"] == "alice" and row["m"] == "AGENT" and row["r"] == 2
    assert row["ps"] == "PENDING_REVIEW" and row["pa"] == "arn:old"
    assert REASON not in json.dumps(audits)


def test_failed_claim_is_rerun_without_stopping(monkeypatch):
    sfn = FakeSfn()
    setup(
        monkeypatch,
        status="FAILED",
        update={**OLD, "old_status": "FAILED", "old_token": None, "old_failure": "boom"},
        sfn=sfn,
    )
    assert call()["statusCode"] == 202
    assert [c[0] for c in sfn.calls] == ["start"]


def test_stop_failure_restores_claim_and_starts_nothing(monkeypatch):
    sfn = FakeSfn(stop_error=err("AccessDeniedException"))
    fake = setup(monkeypatch, update=OLD, sfn=sfn)
    res = call()
    assert res["statusCode"] == 502 and [c[0] for c in sfn.calls] == ["stop"]
    restore = next(c for c in fake.calls if "SET status = :s, review_task_token = :t" in " ".join(c[0].split()))[1]
    assert restore["s"] == "PENDING_REVIEW" and restore["t"] == "old-tok" and restore["a"] == "arn:old"
    assert any("status = 'ABORTED'" in c[0] for c in fake.calls)
    assert audit_events(fake)[-1] == (
        "RERUN_ABORTED",
        {"run_id": 2, "cause": "STOP_FAILED", "restored_status": "PENDING_REVIEW"},
    )


def test_already_ended_old_execution_is_ok(monkeypatch):
    sfn = FakeSfn(stop_error=err("ExecutionDoesNotExist"))
    setup(monkeypatch, update=OLD, sfn=sfn)
    assert call()["statusCode"] == 202 and [c[0] for c in sfn.calls] == ["stop", "start"]


def test_pending_review_without_arn_aborts(monkeypatch):
    sfn = FakeSfn()
    fake = setup(monkeypatch, update={**OLD, "old_arn": None}, sfn=sfn)
    assert call()["statusCode"] == 409 and sfn.calls == []
    assert any("status = 'ABORTED'" in c[0] for c in fake.calls)
    assert audit_events(fake)[-1][0] == "RERUN_ABORTED" and audit_events(fake)[-1][1]["cause"] == "NO_EXECUTION_ARN"


def test_start_failure_marks_failed_and_run_start_failed(monkeypatch):
    fake = setup(monkeypatch, update=OLD, sfn=FakeSfn(start_error=err("StateMachineDoesNotExist")))
    assert call()["statusCode"] == 502
    sqls = [" ".join(c[0].split()) for c in fake.calls]
    assert any("SET status = 'FAILED'" in s for s in sqls) and any("status = 'START_FAILED'" in s for s in sqls)
    assert [e for e, _ in audit_events(fake)] == ["RERUN_REQUESTED", "RERUN_START_FAILED"]
    assert all(REASON not in json.dumps(d) for _, d in audit_events(fake))


def test_double_click_only_one_run_starts(monkeypatch):
    sfn = FakeSfn()
    state = {"n": 0}

    def update(sql, params):
        state["n"] += 1
        return [OLD] if state["n"] == 1 else []

    fake = setup(monkeypatch, update=None, sfn=sfn)
    fake.responses[UPDATE] = update
    assert call()["statusCode"] == 202
    # second click: the claim is now AGENT_REVIEW
    fake.responses["SELECT status, final_decision FROM claims"] = [{"status": "AGENT_REVIEW", "final_decision": None}]
    assert call()["statusCode"] == 409
    # a click that passed the pre-check but lost the row race also gets 409 and starts nothing
    fake.responses["SELECT status, final_decision FROM claims"] = [{"status": "PENDING_REVIEW", "final_decision": None}]
    assert call()["statusCode"] == 409
    assert [c[0] for c in sfn.calls] == ["stop", "start"]


def test_decide_cannot_use_token_after_rerun(monkeypatch):
    # decide() needs PENDING_REVIEW and a stored token; the re-run nulled both, so the UPDATE returns no row.
    install(monkeypatch, examiner_reviews, FakeDb({"RETURNING o.old_token AS review_task_token": []}))
    ev = api_event(
        "POST",
        "/reviews/{claimId}/decision",
        groups="examiners",
        provider_id=None,
        path={"claimId": CLAIM},
        body={"decision": "APPROVE", "reason": "late click"},
    )
    assert examiner_reviews.handler(ev, None)["statusCode"] == 409


def test_no_delete_or_part_mutation(monkeypatch):
    fake = setup(monkeypatch, update=OLD)
    call()
    for sql, _ in fake.calls:
        flat = " ".join(sql.upper().split())
        assert "DELETE" not in flat
        assert "UPDATE CLAIM_DOCUMENT_PARTS" not in flat and "UPDATE EXTRACTIONS" not in flat
        assert "INSERT INTO CLAIM_DOCUMENT_PARTS" not in flat and "INSERT INTO EXTRACTIONS" not in flat


def test_review_detail_exposes_runs_and_can_rerun(monkeypatch):
    claim = {
        "claim_id": CLAIM,
        "status": "PENDING_REVIEW",
        "final_decision": None,
        "current_run": 2,
        "submitted_by": "prov",
        "created_at": "t0",
    }
    fake = FakeDb(
        {
            "FROM claims c JOIN providers": [claim],
            "FROM claim_runs": [
                {
                    "run_id": 2,
                    "mode": "AGENT",
                    "requested_by": "alice",
                    "requested_at": "t1",
                    "reason": REASON,
                    "status": "STARTED",
                }
            ],
            "FROM agent_runs WHERE claim_id = :c ORDER BY created_at DESC": [],
            "recommendation->>'decision'": [
                {"claim_run_id": 1, "decision": "APPROVE", "confidence": "0.95"},
                {"claim_run_id": 2, "decision": "PEND", "confidence": "0.6"},
            ],
            "FROM decisions": [
                {
                    "decided_by": "AUTO",
                    "actor": "workflow",
                    "decision": "APPROVE",
                    "reason": "",
                    "created_at": "t",
                    "claim_run_id": 1,
                }
            ],
            "SELECT COUNT(*) AS n FROM document_batches": [{"n": 0}],
        }
    )
    install(monkeypatch, examiner_reviews, fake)
    monkeypatch.setattr(examiner_reviews, "s3", FakeS3())
    ev = api_event("GET", "/reviews/{claimId}", groups="examiners", provider_id=None, path={"claimId": CLAIM})
    data = json.loads(examiner_reviews.handler(ev, None)["body"])
    assert data["can_rerun"] is True and data["current_run"] == 2
    r1, r2 = data["runs"]
    assert (r1["run_id"], r1["mode"], r1["outcome"], r1["final_decision"], r1["agent_decision"]) == (
        1,
        "INITIAL",
        "APPROVE",
        "APPROVE",
        "APPROVE",
    )
    assert (r2["run_id"], r2["requested_by"], r2["reason"], r2["outcome"]) == (2, "alice", REASON, "PENDING_REVIEW")


def detail_for(monkeypatch, status, s3):
    claim = {"claim_id": CLAIM, "status": status, "final_decision": None, "current_run": 1, "created_at": "t0"}
    fake = FakeDb(
        {
            "FROM claims c JOIN providers": [claim],
            "SELECT COUNT(*) AS n FROM document_batches": [{"n": 0}],
        }
    )
    install(monkeypatch, examiner_reviews, fake)
    monkeypatch.setattr(examiner_reviews, "s3", s3)
    monkeypatch.setenv("BDA_OUTPUT_BUCKET", "out")
    ev = api_event("GET", "/reviews/{claimId}", groups="examiners", provider_id=None, path={"claimId": CLAIM})
    return json.loads(examiner_reviews.handler(ev, None)["body"])


def detail_final(monkeypatch, status, final):
    claim = {"claim_id": CLAIM, "status": status, "final_decision": final, "current_run": 1, "created_at": "t0"}
    fake = FakeDb({"FROM claims c JOIN providers": [claim], "SELECT COUNT(*) AS n FROM document_batches": [{"n": 0}]})
    install(monkeypatch, examiner_reviews, fake)
    monkeypatch.setattr(examiner_reviews, "s3", FakeS3())
    ev = api_event("GET", "/reviews/{claimId}", groups="examiners", provider_id=None, path={"claimId": CLAIM})
    return json.loads(examiner_reviews.handler(ev, None)["body"])["can_rerun"]


@pytest.mark.parametrize(
    "status,final,expected",
    [
        ("PENDED_INFO_REQUESTED", "PEND", True),
        ("PENDING_REVIEW", None, True),
        ("APPROVED", "APPROVE", False),
        ("DENIED", "DENY", False),
        ("AGENT_REVIEW", None, False),
    ],
)
def test_can_rerun_by_status_and_final_decision(monkeypatch, status, final, expected):
    assert detail_final(monkeypatch, status, final) is expected


def test_failed_claim_without_stored_case_cannot_rerun(monkeypatch):
    assert detail_for(monkeypatch, "FAILED", FakeS3(missing=True))["can_rerun"] is False


def test_failed_claim_with_stored_case_can_rerun(monkeypatch):
    assert detail_for(monkeypatch, "FAILED", FakeS3())["can_rerun"] is True


def test_pending_review_does_not_check_for_case(monkeypatch):
    # No S3 call per page view for the common case; the rerun endpoint still verifies the case itself.
    assert detail_for(monkeypatch, "PENDING_REVIEW", FakeS3(missing=True))["can_rerun"] is True


# --- workflow side -------------------------------------------------------------------------------------------------


class S3Stub:
    def __init__(self):
        self.put = {}

    def get_object(self, Bucket, Key):
        import io

        return {"Body": io.BytesIO(b'{"form": {}}')}

    def put_object(self, Bucket, Key, Body):
        self.put[Key] = Body


class AgentStub:
    def invoke_agent_runtime(self, **kw):
        import io

        rec = {
            "claim_id": CLAIM,
            "decision": "APPROVE",
            "confidence": 0.99,
            "all_checks_passed": True,
            "line_decisions": [],
            "findings": [],
        }
        return {"response": io.BytesIO(json.dumps(rec).encode()), "runtimeSessionId": CLAIM}


def run_invoke(monkeypatch, current_run):
    monkeypatch.setenv("BDA_OUTPUT_BUCKET", "out")
    monkeypatch.setenv("AGENT_RUNTIME_ARN", "arn:rt")
    fake = FakeDb({"FROM claims c": [{"total_charges": 100, "current_run": current_run, "auto_approve_limit": 5000}]})
    install(monkeypatch, invoke_agent, fake)
    s3 = S3Stub()
    monkeypatch.setattr(invoke_agent, "s3", s3)
    monkeypatch.setattr(invoke_agent, "agentcore", AgentStub())
    monkeypatch.setattr(invoke_agent, "route", lambda *a, **k: ("AUTO", "ok"))
    out = invoke_agent.handler({"claim_id": CLAIM, "case_key": f"claims/{CLAIM}/case.json"}, None)
    return out, fake, s3


def test_run_one_can_auto_route_and_is_attributed(monkeypatch):
    out, fake, s3 = run_invoke(monkeypatch, 1)
    assert out["route"] == "AUTO" and out["run_id"] == 1
    insert = next(c for c in fake.calls if "INSERT INTO agent_runs" in c[0])[1]
    assert insert["n"] == 1
    assert f"claims/{CLAIM}/runs/1/case.json" in s3.put and f"claims/{CLAIM}/runs/1/recommendation.json" in s3.put
    assert f"claims/{CLAIM}/recommendation.json" in s3.put


def test_rerun_never_auto_finalizes_and_reason_is_fixed_text(monkeypatch):
    out, fake, s3 = run_invoke(monkeypatch, 3)
    assert out["route"] == "REVIEW" and out["run_id"] == 3
    assert out["route_reason"] == "Re-run of the agent review (run 3); every re-run is reviewed by a human"
    assert next(c for c in fake.calls if "INSERT INTO agent_runs" in c[0])[1]["n"] == 3
    assert f"claims/{CLAIM}/runs/3/case.json" in s3.put


def test_finalize_records_claim_run_and_pend_stays_final_decision(monkeypatch):
    fake = FakeDb()
    install(monkeypatch, finalize, fake)
    out = finalize.handler({"claim_id": CLAIM, "decision": "PEND", "reason": "need info"}, None)
    assert out["status"] == "PENDED_INFO_REQUESTED"
    assert "SELECT current_run FROM claims" in next(c for c in fake.calls if "INSERT INTO decisions" in c[0])[0]
    upd = next(c for c in fake.calls if "UPDATE claims SET status" in c[0])
    assert upd[1]["d"] == "PEND"
