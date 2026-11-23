"""Thin RDS Data API helper (Aurora PostgreSQL). No DB driver or VPC access needed in Lambda."""

from __future__ import annotations

import datetime as dt
import decimal
import json
import os
from dataclasses import dataclass
from typing import Any

import boto3

_client = None


def _rds():
    global _client
    if _client is None:
        _client = boto3.client("rds-data")
    return _client


@dataclass(frozen=True)
class Typed:
    """Explicit type hint for a parameter: DATE, TIMESTAMP, DECIMAL or JSON."""

    value: Any
    hint: str


def _param(name: str, value: Any) -> dict[str, Any]:
    hint = None
    if isinstance(value, Typed):
        hint, value = value.hint, value.value
    if value is None:
        field: dict[str, Any] = {"isNull": True}
    elif isinstance(value, bool):
        field = {"booleanValue": value}
    elif isinstance(value, int):
        field = {"longValue": value}
    elif isinstance(value, float):
        field = {"doubleValue": value}
    elif isinstance(value, decimal.Decimal):
        field, hint = {"stringValue": str(value)}, hint or "DECIMAL"
    elif isinstance(value, dt.datetime):
        field, hint = {"stringValue": value.strftime("%Y-%m-%d %H:%M:%S")}, hint or "TIMESTAMP"
    elif isinstance(value, dt.date):
        field, hint = {"stringValue": value.isoformat()}, hint or "DATE"
    elif isinstance(value, (dict, list)):
        field, hint = {"stringValue": json.dumps(value, default=str)}, hint or "JSON"
    else:
        field = {"stringValue": str(value)}
    param: dict[str, Any] = {"name": name, "value": field}
    if hint and value is not None:
        param["typeHint"] = hint
    return param


def _base() -> dict[str, str]:
    return {
        "resourceArn": os.environ["DB_CLUSTER_ARN"],
        "secretArn": os.environ["DB_SECRET_ARN"],
        "database": os.environ["DB_NAME"],
    }


def query(sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    response = _rds().execute_statement(
        **_base(),
        sql=sql,
        parameters=[_param(k, v) for k, v in (params or {}).items()],
        formatRecordsAs="JSON",
    )
    return json.loads(response.get("formattedRecords") or "[]")


def query_one(sql: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
    rows = query(sql, params)
    return rows[0] if rows else None


def execute(sql: str, params: dict[str, Any] | None = None) -> int:
    response = _rds().execute_statement(
        **_base(), sql=sql, parameters=[_param(k, v) for k, v in (params or {}).items()]
    )
    return int(response.get("numberOfRecordsUpdated", 0))


def execute_many(sql: str, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    for start in range(0, len(rows), 200):
        _rds().batch_execute_statement(
            **_base(),
            sql=sql,
            parameterSets=[[_param(k, v) for k, v in row.items()] for row in rows[start : start + 200]],
        )


def audit(claim_id: str, actor: str, event_type: str, detail: dict[str, Any] | None = None) -> None:
    execute(
        "INSERT INTO audit_events (claim_id, actor, event_type, detail) VALUES (:c, :a, :e, :d)",
        {"c": claim_id, "a": actor, "e": event_type, "d": Typed(detail or {}, "JSON")},
    )
