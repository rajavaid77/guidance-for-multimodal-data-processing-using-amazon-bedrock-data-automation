"""Step Functions task: invoke the Strands claims reviewer on AgentCore Runtime and decide the route."""

from __future__ import annotations

import json
import os
from typing import Any

import boto3
from botocore.config import Config

from common import db

from .routing import route

s3 = boto3.client("s3")
agentcore = boto3.client("bedrock-agentcore", config=Config(read_timeout=900, retries={"max_attempts": 1}))

REQUIRED = {"claim_id", "decision", "confidence", "all_checks_passed", "line_decisions", "findings"}


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    claim_id = event["claim_id"]
    bucket = os.environ["BDA_OUTPUT_BUCKET"]
    case_body = s3.get_object(Bucket=bucket, Key=event["case_key"])["Body"].read()
    case = json.loads(case_body)
    claim = db.query_one(
        """SELECT c.total_charges, c.current_run, p.auto_approve_limit FROM claims c
           LEFT JOIN members m ON m.member_id = c.member_id LEFT JOIN plans p ON p.plan_id = m.plan_id
           WHERE c.claim_id = :id""",
        {"id": claim_id},
    )
    # The run is read server-side so a re-run can never be routed as run 1 by dropping an input field.
    run_id = int((claim or {}).get("current_run") or 1)

    response = agentcore.invoke_agent_runtime(
        agentRuntimeArn=os.environ["AGENT_RUNTIME_ARN"],
        qualifier="DEFAULT",
        runtimeSessionId=claim_id,  # CLM-<32 hex> = 36 chars (>= 33 required)
        runtimeUserId=os.environ.get("RUNTIME_USER_ID", "claims-workflow"),
        contentType="application/json",
        accept="application/json",
        payload=json.dumps({"claim_id": claim_id, "case": case}).encode(),
    )
    recommendation = json.loads(response["response"].read())
    missing = REQUIRED - set(recommendation)
    if missing or recommendation.get("claim_id") != claim_id:
        raise ValueError(f"Invalid recommendation from agent runtime, missing {sorted(missing)}")

    rec_key = f"claims/{claim_id}/recommendation.json"
    run_prefix = f"claims/{claim_id}/runs/{run_id}"
    # Per-run snapshots keep the input and output of every run; the legacy key always holds the latest.
    s3.put_object(Bucket=bucket, Key=f"{run_prefix}/case.json", Body=case_body)
    s3.put_object(Bucket=bucket, Key=f"{run_prefix}/recommendation.json", Body=json.dumps(recommendation).encode())
    s3.put_object(Bucket=bucket, Key=rec_key, Body=json.dumps(recommendation).encode())
    db.execute(
        """INSERT INTO agent_runs (claim_id, session_id, prompt_version, models, recommendation, claim_run_id)
           VALUES (:c, :s, :p, :m, :r, :n)""",
        {
            "c": claim_id,
            "s": response.get("runtimeSessionId", claim_id),
            "p": recommendation.get("prompt_version"),
            "m": json.dumps(recommendation.get("models", {})),
            "r": db.Typed(recommendation, "JSON"),
            "n": run_id,
        },
    )
    decision_route, reason = route(
        recommendation,
        float(claim["total_charges"]) if claim and claim.get("total_charges") is not None else None,
        float(claim["auto_approve_limit"]) if claim and claim.get("auto_approve_limit") is not None else None,
        float(os.environ.get("AUTO_APPROVE_MIN_CONFIDENCE", "0.9")),
        float(os.environ.get("AUTO_APPROVE_MAX_AMOUNT", "1000")),
    )
    if run_id > 1:
        # Never auto-finalize a re-run. The fixed text carries no examiner-entered reason (it goes to SNS).
        decision_route = "REVIEW"
        reason = f"Re-run of the agent review (run {run_id}); every re-run is reviewed by a human"
    db.execute(
        "UPDATE claims SET agent_decision = :d, agent_confidence = :c, updated_at = now() WHERE claim_id = :id",
        {"d": recommendation["decision"], "c": float(recommendation["confidence"]), "id": claim_id},
    )
    db.audit(
        claim_id,
        "workflow",
        "AGENT_RECOMMENDATION",
        {"decision": recommendation["decision"], "route": decision_route, "reason": reason, "run_id": run_id},
    )
    return {
        "claim_id": claim_id,
        "route": decision_route,
        "route_reason": reason,
        "decision": recommendation["decision"],
        "line_decisions": recommendation["line_decisions"],
        "recommendation_key": rec_key,
        "run_id": run_id,
    }
