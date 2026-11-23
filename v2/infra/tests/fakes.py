"""In-memory stand-ins for the Data API helper, keyed by SQL substrings."""

from __future__ import annotations

import re
from typing import Any


class FakeDb:
    def __init__(self, responses: dict[str, Any] | None = None, updated: dict[str, int] | None = None):
        self.responses = responses or {}
        self.updated = updated or {}
        self.calls: list[tuple[str, dict]] = []

    def _match(self, table: dict, sql: str, default):
        flat = re.sub(r"\s+", " ", sql)
        for needle, value in table.items():
            if needle in flat:
                return value(flat, self.calls[-1][1]) if callable(value) else value
        return default

    def query(self, sql, params=None):
        self.calls.append((sql, params or {}))
        return self._match(self.responses, sql, [])

    def query_one(self, sql, params=None):
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def execute(self, sql, params=None):
        self.calls.append((sql, params or {}))
        return self._match(self.updated, sql, 1)

    def execute_many(self, sql, rows):
        self.calls.append((sql, {"rows": rows}))

    def audit(self, *args, **kwargs):
        self.calls.append(("AUDIT", {"args": args}))


def install(monkeypatch, module, fake: FakeDb):
    for name in ("query", "query_one", "execute", "execute_many", "audit"):
        monkeypatch.setattr(module.db, name, getattr(fake, name))


def api_event(method, resource, *, groups="providers", provider_id="PRV-1001", body=None, path=None, query=None):
    import json

    claims = {"sub": "u-1", "cognito:username": "alice", "cognito:groups": groups}
    if provider_id:
        claims["custom:provider_id"] = provider_id
    return {
        "httpMethod": method,
        "resource": resource,
        "pathParameters": path,
        "queryStringParameters": query,
        "body": json.dumps(body) if body is not None else None,
        "requestContext": {"authorizer": {"claims": claims}},
    }
