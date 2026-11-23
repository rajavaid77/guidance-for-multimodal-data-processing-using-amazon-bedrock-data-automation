"""API Gateway (REST, Lambda proxy) helpers."""

from __future__ import annotations

import datetime as dt
import decimal
import json
import os
from typing import Any


class _Encoder(json.JSONEncoder):
    def default(self, o: Any) -> Any:
        if isinstance(o, decimal.Decimal):
            return float(o)
        if isinstance(o, (dt.date, dt.datetime)):
            return o.isoformat()
        return super().default(o)


def response(status: int, body: Any) -> dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": os.environ.get("ALLOWED_ORIGIN", ""),
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
        "body": json.dumps(body, cls=_Encoder),
    }


def body_json(event: dict[str, Any]) -> dict[str, Any]:
    raw = event.get("body") or "{}"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("Request body must be JSON") from exc
    if not isinstance(data, dict):
        raise ValueError("Request body must be a JSON object")
    return data
