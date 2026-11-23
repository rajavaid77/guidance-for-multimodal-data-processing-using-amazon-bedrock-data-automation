"""Action-level authorization on top of the API Gateway Cognito authorizer.

The authorizer proves who the caller is; these helpers decide what they may do:
- `providers` group members act only on claims of their own `custom:provider_id`.
- `examiners` group members may read and decide any claim in review.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

PROVIDERS = "providers"
EXAMINERS = "examiners"


class Forbidden(Exception):
    pass


@dataclass(frozen=True)
class Caller:
    sub: str
    username: str
    groups: frozenset[str]
    provider_id: str | None

    def require(self, group: str) -> None:
        if group not in self.groups:
            raise Forbidden(f"Caller is not in group {group}")


def _groups(raw: Any) -> frozenset[str]:
    if isinstance(raw, list):
        return frozenset(str(g) for g in raw)
    if not raw:
        return frozenset()
    return frozenset(g for g in re.split(r"[\s,\[\]]+", str(raw)) if g)


def caller_from_event(event: dict[str, Any]) -> Caller:
    claims = (event.get("requestContext") or {}).get("authorizer", {}).get("claims")
    if not claims or not claims.get("sub"):
        # The Cognito authorizer must have run; fail closed if it did not.
        raise Forbidden("Missing authorizer claims")
    return Caller(
        sub=claims["sub"],
        username=claims.get("cognito:username") or claims.get("email") or claims["sub"],
        groups=_groups(claims.get("cognito:groups")),
        provider_id=claims.get("custom:provider_id") or None,
    )
