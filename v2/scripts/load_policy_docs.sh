#!/usr/bin/env bash
# Upload additional plan policy documents (PDF) and re-sync the knowledge base.
#   ./load_policy_docs.sh path/to/Evidence_of_Coverage_-_AnyHealth_Gold.pdf [...]
# File names must contain the plan name with underscores (e.g. AnyHealth_Gold) - see agents/claims_agents/kb.py.
set -euo pipefail
STACK="${STACK_NAME:-agentic-claims-v2}"; REGION="${AWS_REGION:-us-west-2}"
out() { aws cloudformation describe-stacks --region "$REGION" --stack-name "$STACK" \
  --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text; }
BUCKET=$(out PolicyBucket); KB=$(out KnowledgeBaseId); DS=$(out DataSourceId)
for f in "$@"; do aws s3 cp --region "$REGION" "$f" "s3://$BUCKET/eoc/$(basename "$f")" --sse aws:kms; done
JOB=$(aws bedrock-agent start-ingestion-job --region "$REGION" --knowledge-base-id "$KB" --data-source-id "$DS" \
  --query ingestionJob.ingestionJobId --output text)
echo "Started ingestion job $JOB"
