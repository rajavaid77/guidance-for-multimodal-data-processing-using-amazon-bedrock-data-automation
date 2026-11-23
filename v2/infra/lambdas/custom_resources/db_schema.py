"""CloudFormation custom resource: apply db/schema.sql and db/seed.sql through the RDS Data API (idempotent)."""

from __future__ import annotations

import time
from typing import Any

import boto3

from common import db

s3 = boto3.client("s3")


def _statements(bucket: str, key: str) -> list[str]:
    text = s3.get_object(Bucket=bucket, Key=key)["Body"].read().decode()
    lines = [line for line in text.splitlines() if not line.strip().startswith("--")]
    return [stmt.strip() for stmt in "\n".join(lines).split(";") if stmt.strip()]


def _run_with_resume_retry(sql: str) -> None:
    for attempt in range(12):
        try:
            db.execute(sql)
            return
        except Exception as exc:  # Serverless v2 may be resuming / Data API warming up
            if "DatabaseResumingException" not in repr(exc) and "Communications link failure" not in repr(exc):
                raise
            time.sleep(min(5 * (attempt + 1), 30))
    raise TimeoutError("Database did not become available")


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    if event["RequestType"] == "Delete":
        return {"PhysicalResourceId": event.get("PhysicalResourceId", "db-schema")}
    props = event["ResourceProperties"]
    for key in (props["SchemaKey"], props["SeedKey"]):
        for stmt in _statements(props["Bucket"], key):
            _run_with_resume_retry(stmt)
    return {"PhysicalResourceId": "db-schema", "Data": {"Applied": props.get("Version", "")}}
