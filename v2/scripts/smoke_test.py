#!/usr/bin/env python3
"""End-to-end smoke test for a deployed stack (run with operator AWS credentials).

1. Verifies every API route rejects anonymous callers (expects 401 from the Cognito authorizer).
2. Submits a sample CMS-1500 through the provider API Lambda (direct invoke with a synthetic authorizer context -
   this needs lambda:InvokeFunction and bypasses Cognito sign-in, which is exercised manually through the UI).
3. Waits for the workflow to reach examiner review (or auto-finalize), then approves as an examiner.

Usage: python smoke_test.py [path/to/cms1500.pdf] [--provider-id PRV-1001]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import boto3

REPO = Path(__file__).resolve().parents[2]
DEFAULT_FORM = REPO / "assets" / "data" / "claims_review" / "cms_1500" / "sample1_cms-1500-P.pdf"
TERMINAL = {"APPROVED", "DENIED", "PENDED_INFO_REQUESTED", "FAILED"}


def outputs(cfn, stack: str) -> dict[str, str]:
    stack_desc = cfn.describe_stacks(StackName=stack)["Stacks"][0]
    return {o["OutputKey"]: o["OutputValue"] for o in stack_desc["Outputs"]}


def check_anonymous_denied(api_url: str) -> None:
    claim = "CLM-" + "0" * 32
    for method, path in [
        ("GET", "claims"),
        ("POST", "claims"),
        ("GET", f"claims/{claim}"),
        ("POST", f"claims/{claim}/submit"),
        ("GET", "reviews"),
        ("GET", f"reviews/{claim}"),
        ("POST", f"reviews/{claim}/decision"),
    ]:
        req = urllib.request.Request(api_url + path, method=method, data=b"{}" if method == "POST" else None)
        try:
            urllib.request.urlopen(req, timeout=15)  # noqa: S310 - our own API URL
            raise SystemExit(f"FAIL: anonymous {method} /{path} was allowed")
        except urllib.error.HTTPError as err:
            if err.code != 401:
                raise SystemExit(f"FAIL: anonymous {method} /{path} returned {err.code}, expected 401") from err
    print("OK  anonymous requests are rejected with 401 on every route")


def call(
    lam,
    fn: str,
    method: str,
    resource: str,
    *,
    groups: str,
    provider_id: str | None = None,
    path: dict | None = None,
    body: dict | None = None,
    query: dict | None = None,
) -> tuple[int, dict]:
    claims = {
        "sub": "smoke-test",
        "cognito:username": f"smoke-{groups}",
        "cognito:groups": groups,
    }
    if provider_id:
        claims["custom:provider_id"] = provider_id
    event = {
        "httpMethod": method,
        "resource": resource,
        "pathParameters": path,
        "queryStringParameters": query,
        "body": json.dumps(body) if body is not None else None,
        "requestContext": {"authorizer": {"claims": claims}},
    }
    res = json.loads(lam.invoke(FunctionName=fn, Payload=json.dumps(event).encode())["Payload"].read())
    return res["statusCode"], json.loads(res["body"])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("form", nargs="?", default=str(DEFAULT_FORM))
    parser.add_argument("--provider-id", default="PRV-1001")
    parser.add_argument("--stack", default="agentic-claims-v2")
    parser.add_argument("--region", default="us-west-2")
    parser.add_argument("--timeout", type=int, default=1200)
    args = parser.parse_args()

    session = boto3.Session(region_name=args.region)
    out = outputs(session.client("cloudformation"), args.stack)
    lam = session.client("lambda")
    check_anonymous_denied(out["ApiUrl"])

    form = Path(args.form)
    status, created = call(
        lam,
        out["ProviderApiFunction"],
        "POST",
        "/claims",
        groups="providers",
        provider_id=args.provider_id,
        body={
            "documents": [
                {
                    "file_name": form.name,
                    "content_type": "application/pdf",
                    "declared_type": "CMS1500",
                }
            ]
        },
    )
    assert status == 201, created
    claim_id = created["claim_id"]
    upload = created["uploads"][0]
    req = urllib.request.Request(
        upload["upload_url"],
        data=form.read_bytes(),
        method="PUT",
        headers={"Content-Type": "application/pdf"},
    )
    urllib.request.urlopen(req, timeout=60)  # noqa: S310 - pre-signed S3 URL
    status, submitted = call(
        lam,
        out["ProviderApiFunction"],
        "POST",
        "/claims/{claimId}/submit",
        groups="providers",
        provider_id=args.provider_id,
        path={"claimId": claim_id},
        body={},
    )
    assert status == 202, submitted
    print(f"OK  submitted {claim_id}")

    deadline, last = time.time() + args.timeout, None
    while time.time() < deadline:
        status, detail = call(
            lam,
            out["ExaminerApiFunction"],
            "GET",
            "/reviews/{claimId}",
            groups="examiners",
            path={"claimId": claim_id},
        )
        state = detail["claim"]["status"]
        if state != last:
            print(f"..  status {state}")
            last = state
        if state == "PENDING_REVIEW":
            rec = detail["recommendation"]
            print(f"OK  agent recommended {rec['decision']} ({rec['confidence']:.0%}); {len(rec['findings'])} findings")
            for f in rec["findings"][:10]:
                print(f"      {f['severity']:<7} {f['code']}: {f['message'][:110]}")
            status, decided = call(
                lam,
                out["ExaminerApiFunction"],
                "POST",
                "/reviews/{claimId}/decision",
                groups="examiners",
                path={"claimId": claim_id},
                body={
                    "decision": rec["decision"],
                    "reason": "Smoke test: accept agent recommendation",
                    "line_decisions": rec["line_decisions"],
                },
            )
            assert status == 202, decided
        if state in TERMINAL:
            print(
                f"{'OK ' if state != 'FAILED' else 'FAIL'} final status {state} {detail['claim'].get('failure_reason') or ''}"
            )
            return 0 if state != "FAILED" else 1
        time.sleep(15)
    print("FAIL timed out")
    return 1


if __name__ == "__main__":
    sys.exit(main())
