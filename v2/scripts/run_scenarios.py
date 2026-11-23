#!/usr/bin/env python3
"""Submit the synthetic test scenarios (assets/data/claims_review/test_scenarios/scenarios.json) to a deployed stack.

Each scenario is submitted through the provider API Lambda (direct invoke with a synthetic authorizer context, like
smoke_test.py), its documents are uploaded via the pre-signed URLs, and the script waits until the agents have
produced a recommendation. Claims are LEFT IN THE EXAMINER QUEUE (PENDING_REVIEW) so they can be reviewed in the UI,
unless --decide is given (accepts the agent recommendation).

Usage: python run_scenarios.py [--only S1,S5] [--decide] [--stack agentic-claims-v2]
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.request
from pathlib import Path

import boto3

REPO = Path(__file__).resolve().parents[2]
MANIFEST = REPO / "assets" / "data" / "claims_review" / "test_scenarios" / "scenarios.json"
WAITING = {"DRAFT", "SUBMITTED", "EXTRACTING", "AGENT_REVIEW", "FINALIZING"}
CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}


def call(lam, fn, method, resource, *, groups, provider_id=None, path=None, body=None):
    claims = {
        "sub": "scenario-runner",
        "cognito:username": f"scenario-{groups}",
        "cognito:groups": groups,
    }
    if provider_id:
        claims["custom:provider_id"] = provider_id
    event = {
        "httpMethod": method,
        "resource": resource,
        "pathParameters": path,
        "queryStringParameters": None,
        "body": json.dumps(body) if body is not None else None,
        "requestContext": {"authorizer": {"claims": claims}},
    }
    res = json.loads(lam.invoke(FunctionName=fn, Payload=json.dumps(event).encode())["Payload"].read())
    return res["statusCode"], json.loads(res["body"])


def submit(lam, fn, scenario) -> str:
    docs = [{"path": REPO / d["path"], "type": d["type"]} for d in scenario["documents"]]
    status, created = call(
        lam,
        fn,
        "POST",
        "/claims",
        groups="providers",
        provider_id=scenario["provider_id"],
        body={
            "documents": [
                {
                    "file_name": d["path"].name,
                    "content_type": CONTENT_TYPES[d["path"].suffix.lower()],
                    "declared_type": d["type"],
                }
                for d in docs
            ]
        },
    )
    assert status == 201, created
    for d, up in zip(docs, created["uploads"], strict=True):
        req = urllib.request.Request(
            up["upload_url"],
            data=d["path"].read_bytes(),
            method="PUT",
            headers={"Content-Type": up["content_type"]},
        )
        urllib.request.urlopen(req, timeout=60)  # noqa: S310 - pre-signed S3 URL
    status, body = call(
        lam,
        fn,
        "POST",
        "/claims/{claimId}/submit",
        groups="providers",
        provider_id=scenario["provider_id"],
        path={"claimId": created["claim_id"]},
        body={},
    )
    assert status == 202, body
    return created["claim_id"]


def report(scenario, detail) -> None:
    rec = detail.get("recommendation") or {}
    print(
        f"\n=== {scenario['id']}  {scenario['title']}\n    claim {detail['claim']['claim_id']}  "
        f"status {detail['claim']['status']}"
    )
    print(f"    expected: {scenario['expected']}")
    if not rec:
        print(f"    no recommendation ({detail['claim'].get('failure_reason') or ''})")
        return
    print(f"    agent:    {rec['decision']} ({rec['confidence']:.0%})  checks {rec['checks']}")
    for d in rec["line_decisions"]:
        codes = "/".join(c for c in (d.get("carc"), d.get("rarc")) if c)
        print(f"      line {d['line_number']}: {d['decision']:<7} {codes:<10} {d['reason'][:110]}")
    errors = [f for f in rec["findings"] if f["severity"] == "ERROR"]
    print(
        f"    {len(rec['findings'])} findings, {len(errors)} errors: " + ", ".join(sorted({f["code"] for f in errors}))
    )


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--only", help="comma-separated scenario ids")
    p.add_argument(
        "--decide",
        action="store_true",
        help="accept the agent recommendation as examiner",
    )
    p.add_argument("--stack", default="agentic-claims-v2")
    p.add_argument("--region", default="us-west-2")
    p.add_argument("--timeout", type=int, default=1800)
    args = p.parse_args()

    scenarios = json.loads(MANIFEST.read_text())["scenarios"]
    if args.only:
        wanted = set(args.only.split(","))
        scenarios = [s for s in scenarios if s["id"] in wanted]
    session = boto3.Session(region_name=args.region)
    out = {
        o["OutputKey"]: o["OutputValue"]
        for o in session.client("cloudformation").describe_stacks(StackName=args.stack)["Stacks"][0]["Outputs"]
    }
    lam = session.client("lambda")

    pending = {}
    for s in scenarios:
        pending[submit(lam, out["ProviderApiFunction"], s)] = s
        print(f"submitted {s['id']} -> {list(pending)[-1]}")

    deadline = time.time() + args.timeout
    while pending and time.time() < deadline:
        time.sleep(20)
        for claim_id, s in list(pending.items()):
            _, detail = call(
                lam,
                out["ExaminerApiFunction"],
                "GET",
                "/reviews/{claimId}",
                groups="examiners",
                path={"claimId": claim_id},
            )
            if detail["claim"]["status"] in WAITING:
                continue
            report(s, detail)
            if args.decide and detail["claim"]["status"] == "PENDING_REVIEW":
                rec = detail["recommendation"]
                call(
                    lam,
                    out["ExaminerApiFunction"],
                    "POST",
                    "/reviews/{claimId}/decision",
                    groups="examiners",
                    path={"claimId": claim_id},
                    body={
                        "decision": rec["decision"],
                        "line_decisions": rec["line_decisions"],
                        "reason": f"Scenario {s['id']}: accept agent recommendation",
                    },
                )
            del pending[claim_id]
    for claim_id, s in pending.items():
        print(f"\n=== {s['id']} timed out ({claim_id})")


if __name__ == "__main__":
    main()
