"""Step Functions task: close an additional-document batch and tell examiners when a claim under review changed."""

from __future__ import annotations

import os
from typing import Any

import boto3

from common import db

sns = boto3.client("sns")


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    claim_id, batch_id, action = event["claim_id"], event["batch_id"], event.get("action")
    db.execute(
        """UPDATE document_batches SET stage = 'DONE', completed_at = now(), task_token = NULL, updated_at = now()
           WHERE batch_id = :b AND claim_id = :c""",
        {"b": batch_id, "c": claim_id},
    )
    if action == "REVIEW_IN_PLACE":
        # No PHI in notifications: claim id and a link only.
        sns.publish(
            TopicArn=os.environ["REVIEW_TOPIC_ARN"],
            Subject="Additional documents added to a claim under review",
            Message=(
                f"Additional documents were added to claim {claim_id} and the AI review was re-run.\n"
                f"Open: {os.environ.get('APP_URL', '')}/examiner/reviews/{claim_id}"
            ),
        )
    db.audit(claim_id, "workflow", "BATCH_DONE", {"batch_id": batch_id, "action": action})
    return {"claim_id": claim_id, "batch_id": batch_id}
