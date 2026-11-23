"""AgentCore Runtime entrypoint.

Invoked by the Step Functions `InvokeAgent` Lambda with SigV4 and a runtime user id, payload:
    {"claim_id": "...", "case": {...ClaimCase...}}
Returns the Recommendation JSON.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from bedrock_agentcore.runtime import BedrockAgentCoreApp

from .config import Settings, load_settings
from .gateway import build_gateway_client, fetch_gateway_token, select_tools
from .kb import make_retrieve_policy_tool
from .models import ClaimCase
from .specialists import bedrock_model
from .supervisor import ClaimReview, SpecialistToolkit

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("claims_agents")

app = BedrockAgentCoreApp()


def review_session_id(claim_id: str) -> str:
    return f"{claim_id}-{uuid.uuid4().hex[:12]}"


def _session_manager(settings: Settings, claim_id: str):
    if not settings.memory_id:
        return None
    from bedrock_agentcore.memory.integrations.strands.config import AgentCoreMemoryConfig
    from bedrock_agentcore.memory.integrations.strands.session_manager import AgentCoreMemorySessionManager

    # One memory session per review run: a re-review (or Step Functions retry) must start fresh instead of
    # restoring the previous run's conversation and skipping the specialists.
    config = AgentCoreMemoryConfig(
        memory_id=settings.memory_id,
        session_id=review_session_id(claim_id),
        actor_id=settings.actor_id,
        default_metadata={"claim_id": claim_id},
    )
    return AgentCoreMemorySessionManager(config, region_name=settings.region)


def review_claim(case: ClaimCase, settings: Settings, access_token: str) -> dict[str, Any]:
    gateway = build_gateway_client(settings, access_token)
    with gateway:
        gateway_tools = gateway.list_tools_sync()
        retrieve_policy = make_retrieve_policy_tool(settings.knowledge_base_id, settings.region)
        toolkit = SpecialistToolkit(
            reasoning_model=bedrock_model(settings, settings.reasoning_model_id),
            fast_model=bedrock_model(settings, settings.fast_model_id),
            validation_tools=[*select_tools(gateway_tools, ["validate_codes", "find_duplicates"]), retrieve_policy],
            eligibility_tools=select_tools(gateway_tools, ["check_eligibility"]),
            clinical_tools=[retrieve_policy],
            adjudication_tools=[*select_tools(gateway_tools, ["save_decision"]), retrieve_policy],
            model_ids={"reasoning": settings.reasoning_model_id, "fast": settings.fast_model_id},
        )
        review = ClaimReview(case, toolkit, settings.prompt_version)
        recommendation = review.run(session_manager=_session_manager(settings, case.claim_id))
    return recommendation.model_dump(mode="json")


@app.entrypoint
async def invoke(payload: dict[str, Any], context: Any = None) -> dict[str, Any]:
    try:
        case = ClaimCase.model_validate(payload["case"])
    except Exception:
        logger.exception("Invalid claim case payload")
        raise
    settings = load_settings()
    logger.info("Reviewing claim %s (%d lines)", case.claim_id, len(case.service_lines))
    token = await fetch_gateway_token(settings)
    # Strands agents run synchronously; keep the event loop free for /ping health checks.
    return await asyncio.to_thread(review_claim, case, settings, token)


if __name__ == "__main__":
    app.run()
