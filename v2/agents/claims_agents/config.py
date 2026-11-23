"""Runtime configuration, injected as AgentCore Runtime environment variables by the CDK stack."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if value is None:
        raise RuntimeError(f"Missing required environment variable {name}")
    return value


@dataclass(frozen=True)
class Settings:
    region: str = field(default_factory=lambda: _env("AWS_REGION", "us-west-2"))
    reasoning_model_id: str = field(default_factory=lambda: _env("REASONING_MODEL_ID"))
    fast_model_id: str = field(default_factory=lambda: _env("FAST_MODEL_ID"))
    guardrail_id: str | None = field(default_factory=lambda: os.environ.get("GUARDRAIL_ID") or None)
    guardrail_version: str | None = field(default_factory=lambda: os.environ.get("GUARDRAIL_VERSION") or None)
    knowledge_base_id: str = field(default_factory=lambda: _env("KNOWLEDGE_BASE_ID"))
    memory_id: str | None = field(default_factory=lambda: os.environ.get("MEMORY_ID") or None)
    gateway_url: str = field(default_factory=lambda: _env("GATEWAY_URL"))
    oauth_provider_name: str = field(default_factory=lambda: _env("GATEWAY_OAUTH_PROVIDER_NAME"))
    oauth_scopes: tuple[str, ...] = field(
        default_factory=lambda: tuple(s for s in _env("GATEWAY_OAUTH_SCOPES", "").split(" ") if s)
    )
    prompt_version: str = field(default_factory=lambda: os.environ.get("PROMPT_VERSION", "1"))
    actor_id: str = field(default_factory=lambda: os.environ.get("MEMORY_ACTOR_ID", "claims-workflow"))


def load_settings() -> Settings:
    return Settings()
