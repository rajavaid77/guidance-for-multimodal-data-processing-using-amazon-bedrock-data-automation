import json

import pytest
from fakes import FakeDb, api_event, install

from api import examiner_reviews, provider_claims
from common.auth import Forbidden, caller_from_event


class FakeS3:
    class exceptions:
        ClientError = Exception

    def generate_presigned_url(self, op, Params, ExpiresIn):
        assert ExpiresIn <= 300
        self.last = (op, Params, ExpiresIn)
        return f"https://s3.example/{Params['Key']}?sig"

    def head_object(self, **kw):
        return {"ContentLength": 10, "ContentType": "application/pdf"}

    def put_object(self, **kw):
        self.put = kw


def test_missing_authorizer_claims_fail_closed():
    with pytest.raises(Forbidden):
        caller_from_event({"requestContext": {}})


def test_groups_parsing():
    caller = caller_from_event(api_event("GET", "/claims", groups="[providers, examiners]"))
    assert caller.groups == {"providers", "examiners"}


def test_examiner_cannot_use_provider_api(monkeypatch):
    install(monkeypatch, provider_claims, FakeDb())
    res = provider_claims.handler(api_event("GET", "/claims", groups="examiners"), None)
    assert res["statusCode"] == 403


def test_provider_cannot_use_examiner_api(monkeypatch):
    install(monkeypatch, examiner_reviews, FakeDb())
    res = examiner_reviews.handler(api_event("GET", "/reviews", groups="providers"), None)
    assert res["statusCode"] == 403


def test_create_claim_requires_exactly_one_form(monkeypatch):
    install(monkeypatch, provider_claims, FakeDb())
    body = {"documents": [{"file_name": "a.pdf", "content_type": "application/pdf", "declared_type": "MEDICAL_RECORD"}]}
    res = provider_claims.handler(api_event("POST", "/claims", body=body), None)
    assert res["statusCode"] == 400


def test_create_claim_returns_presigned_uploads(monkeypatch):
    fake = FakeDb()
    install(monkeypatch, provider_claims, fake)
    monkeypatch.setattr(provider_claims, "s3", FakeS3())
    body = {
        "documents": [
            {"file_name": "../../etc/form 1.pdf", "content_type": "application/pdf", "declared_type": "CMS1500"},
            {"file_name": "note.png", "content_type": "image/png", "declared_type": "MEDICAL_RECORD"},
        ]
    }
    res = provider_claims.handler(api_event("POST", "/claims", body=body), None)
    data = json.loads(res["body"])
    assert res["statusCode"] == 201 and data["claim_id"].startswith("CLM-")
    assert data["uploads"][0]["key"].endswith("/docs/01-form_1.pdf")  # path traversal stripped
    assert res["headers"]["Access-Control-Allow-Origin"] == "https://main.example.amplifyapp.com"


def test_provider_cannot_read_other_providers_claim(monkeypatch):
    install(monkeypatch, provider_claims, FakeDb({"FROM claims WHERE claim_id": []}))
    res = provider_claims.handler(api_event("GET", "/claims/{claimId}", path={"claimId": "CLM-" + "0" * 32}), None)
    assert res["statusCode"] == 404


def test_examiner_decision_conflict_when_not_pending(monkeypatch):
    install(monkeypatch, examiner_reviews, FakeDb({"RETURNING o.old_token AS review_task_token": []}))
    res = examiner_reviews.handler(
        api_event(
            "POST",
            "/reviews/{claimId}/decision",
            groups="examiners",
            provider_id=None,
            path={"claimId": "CLM-" + "a" * 32},
            body={"decision": "APPROVE", "reason": "Looks good"},
        ),
        None,
    )
    assert res["statusCode"] == 409


def test_examiner_decision_resumes_workflow(monkeypatch):
    install(
        monkeypatch,
        examiner_reviews,
        FakeDb({"RETURNING o.old_token AS review_task_token": [{"review_task_token": "tok"}]}),
    )
    sent = {}

    class FakeSfn:
        class exceptions:
            ClientError = Exception

        def send_task_success(self, taskToken, output):
            sent.update(token=taskToken, output=json.loads(output))

    monkeypatch.setattr(examiner_reviews, "sfn", FakeSfn())
    res = examiner_reviews.handler(
        api_event(
            "POST",
            "/reviews/{claimId}/decision",
            groups="examiners",
            provider_id=None,
            path={"claimId": "CLM-" + "a" * 32},
            body={"decision": "deny", "reason": "Not covered"},
        ),
        None,
    )
    assert res["statusCode"] == 202
    assert sent["token"] == "tok" and sent["output"]["decision"] == "DENY" and sent["output"]["actor"] == "alice"


def test_token_claims_return_pre_update_value():
    """RETURNING after SET token = NULL would return NULL; both handlers must read the old value."""
    import inspect

    from workflow import bda_callback

    for module in (bda_callback, examiner_reviews):
        source = inspect.getsource(module)
        assert "RETURNING o.old_token" in source, module.__name__


CLAIM = "CLM-" + "0" * 32
BATCH = "BATCH-" + "a" * 32
PART_ROW = {
    "s3_bucket_kind": "OUTPUT",
    "s3_key": "claims/x/parts/1/000.pdf",
    "content_type": "application/pdf",
    "is_original": False,
    "page_start": 1,
}


def _env(monkeypatch):
    monkeypatch.setenv("INTAKE_BUCKET", "intake-b")
    monkeypatch.setenv("BDA_OUTPUT_BUCKET", "output-b")


def _part_event(**kw):
    return api_event("GET", "/claims/{claimId}/parts/{partId}/url", path={"claimId": CLAIM, "partId": "7"}, **kw)


def test_part_url_is_short_lived_and_uses_output_bucket(monkeypatch):
    _env(monkeypatch)
    fake = FakeDb({"FROM claims WHERE claim_id": [{"claim_id": CLAIM}], "FROM claim_document_parts": [PART_ROW]})
    install(monkeypatch, provider_claims, fake)
    s3 = FakeS3()
    monkeypatch.setattr(provider_claims, "s3", s3)
    res = provider_claims.handler(_part_event(), None)
    data = json.loads(res["body"])
    assert res["statusCode"] == 200 and data["expires_in"] == 300 and data["page"] is None
    assert s3.last[1]["Bucket"] == "output-b" and s3.last[2] <= 300


def test_part_url_404_for_other_providers_claim_or_missing_part(monkeypatch):
    _env(monkeypatch)
    install(monkeypatch, provider_claims, FakeDb({"FROM claims WHERE claim_id": []}))
    assert provider_claims.handler(_part_event(), None)["statusCode"] == 404
    install(monkeypatch, provider_claims, FakeDb({"FROM claims WHERE claim_id": [{"claim_id": CLAIM}]}))
    assert provider_claims.handler(_part_event(), None)["statusCode"] == 404


def test_part_url_rejects_examiner_group(monkeypatch):
    install(monkeypatch, provider_claims, FakeDb())
    assert provider_claims.handler(_part_event(groups="examiners"), None)["statusCode"] == 403


def test_examiner_part_url(monkeypatch):
    _env(monkeypatch)
    install(monkeypatch, examiner_reviews, FakeDb({"FROM claim_document_parts": [PART_ROW]}))
    s3 = FakeS3()
    monkeypatch.setattr(examiner_reviews, "s3", s3)
    event = api_event(
        "GET",
        "/reviews/{claimId}/parts/{partId}/url",
        groups="examiners",
        provider_id=None,
        path={"claimId": CLAIM, "partId": "7"},
    )
    res = examiner_reviews.handler(event, None)
    assert res["statusCode"] == 200 and s3.last[2] <= 300
    event["requestContext"]["authorizer"]["claims"]["cognito:groups"] = "providers"
    assert examiner_reviews.handler(event, None)["statusCode"] == 403


def _batch_event(**kw):
    docs = kw.pop("documents", [{"file_name": "a.pdf", "content_type": "application/pdf"}])
    return api_event("POST", "/claims/{claimId}/batches", path={"claimId": CLAIM}, body={"documents": docs})


@pytest.mark.parametrize("status", ["APPROVED", "DENIED", "FAILED", "DRAFT", "FINALIZING", "SUBMITTED"])
def test_batch_conflict_when_claim_not_in_progress(monkeypatch, status):
    _env(monkeypatch)
    install(
        monkeypatch, provider_claims, FakeDb({"FROM claims WHERE claim_id": [{"claim_id": CLAIM, "status": status}]})
    )
    assert provider_claims.handler(_batch_event(), None)["statusCode"] == 409


def test_batch_created_with_auto_type_and_caps(monkeypatch):
    _env(monkeypatch)
    fake = FakeDb(
        {"FROM claims WHERE claim_id": [{"claim_id": CLAIM, "status": "PENDING_REVIEW"}], "SELECT count(*)": [{"n": 5}]}
    )
    install(monkeypatch, provider_claims, fake)
    monkeypatch.setattr(provider_claims, "s3", FakeS3())
    res = provider_claims.handler(_batch_event(), None)
    data = json.loads(res["body"])
    assert res["statusCode"] == 201 and data["batch_id"].startswith("BATCH-") and len(data["uploads"]) == 1
    inserts = [p for sql, p in fake.calls if "INTO claim_documents" in sql]
    assert inserts and "'AUTO'" in [sql for sql, _ in fake.calls if "INTO claim_documents" in sql][0]
    too_many = [{"file_name": f"{i}.pdf", "content_type": "application/pdf"} for i in range(11)]
    assert provider_claims.handler(_batch_event(documents=too_many), None)["statusCode"] == 400
    full = FakeDb(
        {
            "FROM claims WHERE claim_id": [{"claim_id": CLAIM, "status": "PENDING_REVIEW"}],
            "SELECT count(*)": [{"n": 30}],
        }
    )
    install(monkeypatch, provider_claims, full)
    assert provider_claims.handler(_batch_event(), None)["statusCode"] == 400


def test_batch_submit_validates_id_and_queues(monkeypatch):
    _env(monkeypatch)
    fake = FakeDb(
        {
            "FROM claims WHERE claim_id": [{"claim_id": CLAIM, "status": "PENDING_REVIEW"}],
            "FROM document_batches": [{"stage": "UPLOADING"}],
            "FROM claim_documents": [{"s3_key": "k/a.pdf", "content_type": "application/pdf"}],
        }
    )
    install(monkeypatch, provider_claims, fake)
    s3 = FakeS3()
    monkeypatch.setattr(provider_claims, "s3", s3)
    ev = api_event("POST", "/claims/{claimId}/batches/{batchId}/submit", path={"claimId": CLAIM, "batchId": BATCH})
    res = provider_claims.handler(ev, None)
    assert res["statusCode"] == 202 and s3.put["Key"] == f"batches/{CLAIM}/{BATCH}/submit.json"
    ev["pathParameters"]["batchId"] = "BATCH-../x"
    assert provider_claims.handler(ev, None)["statusCode"] == 404


def test_create_claim_auto_form_rule(monkeypatch):
    install(monkeypatch, provider_claims, FakeDb())
    monkeypatch.setattr(provider_claims, "s3", FakeS3())
    monkeypatch.setenv("INTAKE_BUCKET", "intake-b")
    doc = {"file_name": "pack.pdf", "content_type": "application/pdf", "declared_type": "AUTO"}
    assert provider_claims.handler(api_event("POST", "/claims", body={"documents": [doc]}), None)["statusCode"] == 201
    two = {**doc, "declared_type": "CMS1500"}
    assert (
        provider_claims.handler(api_event("POST", "/claims", body={"documents": [two, two]}), None)["statusCode"] == 400
    )
