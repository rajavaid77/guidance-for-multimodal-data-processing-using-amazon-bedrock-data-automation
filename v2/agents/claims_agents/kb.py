"""Policy retrieval tool backed by the Bedrock Knowledge Base (S3 Vectors) holding EoC and coverage policies."""

from __future__ import annotations

from typing import Any

import boto3
from strands import tool


def _page(metadata: dict[str, Any]) -> int | None:
    page = metadata.get("x-amz-bedrock-kb-document-page-number")
    try:
        return int(float(page)) if page is not None else None
    except (TypeError, ValueError):
        return None


def make_retrieve_policy_tool(knowledge_base_id: str, region: str, max_results: int = 6, client: Any = None):
    kb_client = client or boto3.client("bedrock-agent-runtime", region_name=region)

    @tool
    def retrieve_policy(query: str, plan_name: str) -> list[dict[str, Any]]:
        """Search plan benefits (Schedule of Benefits, Evidence of Coverage) and AnyHealth medical/claims policies.

        Args:
            query: What to look up, e.g. "acupuncture visit limits", "modifier 95 place of service" or
                "CARC for missing diagnosis pointer".
            plan_name: The member's plan name on file, e.g. "AnyHealth Plus". Other plans' documents are dropped;
                policies that apply to all plans are kept.

        Returns:
            Passages with `source` (document URI), `page` and `text` to cite verbatim.
        """
        response = kb_client.retrieve(
            knowledgeBaseId=knowledge_base_id,
            retrievalQuery={"text": f"{plan_name}: {query}"},
            retrievalConfiguration={"vectorSearchConfiguration": {"numberOfResults": max_results * 2}},
        )
        plan_token = plan_name.replace(" ", "_").lower()
        passages: list[dict[str, Any]] = []
        for item in response.get("retrievalResults", []):
            location = item.get("location", {}).get("s3Location", {}).get("uri", "")
            shared = "/policies/common/" in location
            if plan_token and not shared and plan_token not in location.lower():
                continue  # another plan's document
            passages.append(
                {
                    "source": location,
                    "page": _page(item.get("metadata", {})),
                    "score": round(float(item.get("score", 0.0)), 3),
                    "text": item.get("content", {}).get("text", ""),
                }
            )
            if len(passages) >= max_results:
                break
        return passages

    return retrieve_policy
