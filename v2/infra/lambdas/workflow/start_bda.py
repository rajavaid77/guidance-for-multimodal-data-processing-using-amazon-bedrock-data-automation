"""Step Functions task (.waitForTaskToken): start one BDA job per uploaded claim document."""

from __future__ import annotations

import os
from typing import Any

import boto3

from common import db

bda = boto3.client("bedrock-data-automation-runtime")


def start_jobs(claim_id: str, documents: list[dict[str, Any]]) -> None:
    """Start one BDA job per document and mark each RUNNING."""
    intake, output = os.environ["INTAKE_BUCKET"], os.environ["BDA_OUTPUT_BUCKET"]
    for doc in documents:
        response = bda.invoke_data_automation_async(
            inputConfiguration={"s3Uri": f"s3://{intake}/{doc['s3_key']}"},
            outputConfiguration={"s3Uri": f"s3://{output}/claims/{claim_id}/{doc['document_id']}"},
            dataAutomationConfiguration={"dataAutomationProjectArn": os.environ["BDA_PROJECT_ARN"], "stage": "LIVE"},
            dataAutomationProfileArn=os.environ["BDA_PROFILE_ARN"],
            notificationConfiguration={"eventBridgeConfiguration": {"eventBridgeEnabled": True}},
            encryptionConfiguration={"kmsKeyId": os.environ["KMS_KEY_ARN"]},
            tags=[{"key": "claim_id", "value": claim_id}],
        )
        db.execute(
            "UPDATE claim_documents SET bda_invocation_arn = :a, bda_status = 'RUNNING' WHERE document_id = :d",
            {"a": response["invocationArn"], "d": doc["document_id"]},
        )


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    key = event["key"]  # claims/{claim_id}/submit.json
    parts = key.split("/")
    if len(parts) != 3 or parts[0] != "claims" or parts[2] != "submit.json":
        raise ValueError(f"Unexpected trigger key {key}")
    claim_id = parts[1]

    updated = db.execute(
        """UPDATE claims SET status = 'EXTRACTING', bda_task_token = :t, execution_arn = :x, updated_at = now()
           WHERE claim_id = :id AND status = 'SUBMITTED'""",
        {"t": event["task_token"], "x": event.get("execution_arn"), "id": claim_id},
    )
    if updated != 1:
        raise RuntimeError(f"Claim {claim_id} is not in SUBMITTED state")

    documents = db.query(
        "SELECT document_id, s3_key FROM claim_documents WHERE claim_id = :id AND batch_id IS NULL ORDER BY document_id",
        {"id": claim_id},
    )
    if not documents:
        raise RuntimeError(f"Claim {claim_id} has no documents")

    start_jobs(claim_id, documents)
    db.audit(claim_id, "workflow", "EXTRACTION_STARTED", {"documents": len(documents)})
    return {"claim_id": claim_id, "documents": len(documents)}
