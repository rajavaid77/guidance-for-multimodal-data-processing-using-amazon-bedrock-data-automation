"""Specialist agents. Each runs a fresh Strands Agent with a typed (Pydantic) structured output."""

from __future__ import annotations

import json
from importlib import resources
from typing import Any

from pydantic import BaseModel
from strands import Agent
from strands.models import BedrockModel

from .config import Settings


def load_prompt(name: str) -> str:
    return resources.files("claims_agents.prompts").joinpath(f"{name}.md").read_text(encoding="utf-8")


def bedrock_model(settings: Settings, model_id: str, max_tokens: int = 8000) -> BedrockModel:
    # Current Claude models reject `temperature`; rely on model defaults plus typed structured output.
    config: dict[str, Any] = {"model_id": model_id, "max_tokens": max_tokens}
    if settings.guardrail_id and settings.guardrail_version:
        # Guardrail applies to model outputs only: claim inputs legitimately contain PHI the agents must read.
        config.update(
            guardrail_id=settings.guardrail_id,
            guardrail_version=settings.guardrail_version,
            guardrail_trace="enabled",
            guardrail_redact_input=False,
        )
    return BedrockModel(region_name=settings.region, **config)


def run_specialist[T: BaseModel](
    *,
    name: str,
    model: Any,
    tools: list[Any],
    payload: dict[str, Any],
    output_model: type[T],
    instruction: str,
) -> T:
    agent = Agent(
        name=name,
        model=model,
        system_prompt=load_prompt(name),
        tools=tools,
        structured_output_model=output_model,
        callback_handler=None,
        trace_attributes={"claims.specialist": name},
    )
    prompt = f"{instruction}\n\n<input>\n{json.dumps(payload, default=str)}\n</input>"
    result = agent(prompt)
    output = result.structured_output
    if not isinstance(output, output_model):
        raise RuntimeError(f"{name} did not return {output_model.__name__}")
    return output
