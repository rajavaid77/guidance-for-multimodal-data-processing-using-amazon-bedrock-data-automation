"""Step Functions task (.waitForTaskToken): queue the claim for an examiner and notify the examiners topic."""

from __future__ import annotations

import os
from typing import Any

import boto3

from common import db

sns = boto3.client("sns")


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    claim_id = event["claim_id"]
    updated = db.execute(
        """UPDATE claims SET status = 'PENDING_REVIEW', review_task_token = :t, updated_at = now()
           WHERE claim_id = :id AND status = 'AGENT_REVIEW'""",
        {"t": event["task_token"], "id": claim_id},
    )
    if updated != 1:
        raise RuntimeError(f"Claim {claim_id} is not in AGENT_REVIEW state")
    db.audit(claim_id, "workflow", "REVIEW_REQUESTED", {"reason": event.get("route_reason")})
    # No PHI in notifications: claim id, agent decision and a link only.
    sns.publish(
        TopicArn=os.environ["REVIEW_TOPIC_ARN"],
        Subject="Claim ready for review",
        Message=(
            f"Claim {claim_id} needs examiner review.\nAgent recommendation: {event.get('decision')}\n"
            f"Reason: {event.get('route_reason')}\nOpen: {os.environ.get('APP_URL', '')}/examiner/reviews/{claim_id}"
        ),
    )
    return {"claim_id": claim_id}
