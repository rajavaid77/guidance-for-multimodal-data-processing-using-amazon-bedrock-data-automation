"""AgentCore Gateway access: OAuth (client credentials) token from AgentCore Identity + Strands MCP client."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from bedrock_agentcore.identity.auth import requires_access_token
from strands.tools.mcp import MCPClient

from .config import Settings

# Gateway prefixes tool names with the target name, e.g. "claims-tools___validate_codes".
TOOL_NAME_SEPARATORS = ("___", "__")


async def fetch_gateway_token(settings: Settings) -> str:
    """Fetch an M2M access token for the Gateway from the AgentCore Identity token vault.

    The OAuth2 credential provider (Cognito client id/secret) is created by the CDK stack; the runtime's workload
    identity is exchanged for the token, so no client secret ever reaches this container.
    """

    @requires_access_token(
        provider_name=settings.oauth_provider_name,
        scopes=list(settings.oauth_scopes),
        auth_flow="M2M",
        into="access_token",
    )
    async def _fetch(*, access_token: str = "") -> str:
        return access_token

    return await _fetch()


def build_gateway_client(settings: Settings, access_token: str) -> MCPClient:
    return MCPClient(url=settings.gateway_url, headers={"Authorization": f"Bearer {access_token}"})


def base_tool_name(full_name: str) -> str:
    for sep in TOOL_NAME_SEPARATORS:
        if sep in full_name:
            return full_name.split(sep)[-1]
    return full_name


def select_tools(tools: Iterable[Any], wanted: Iterable[str]) -> list[Any]:
    """Pick gateway tools by their un-prefixed name."""
    wanted_set = set(wanted)
    selected = [t for t in tools if base_tool_name(getattr(t, "tool_name", "")) in wanted_set]
    missing = wanted_set - {base_tool_name(t.tool_name) for t in selected}
    if missing:
        raise RuntimeError(f"Gateway tools not found: {sorted(missing)}")
    return selected
