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
