# AgentCore Runtime requires linux/arm64 images that listen on port 8080 (/invocations, /ping).
FROM --platform=linux/arm64 public.ecr.aws/docker/library/python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DOCKER_CONTAINER=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml ./
COPY claims_agents ./claims_agents
RUN pip install --upgrade pip && pip install .

RUN useradd --create-home --uid 1000 agent
USER agent

EXPOSE 8080

# opentelemetry-instrument wires Strands spans into AgentCore Observability (CloudWatch GenAI Observability).
CMD ["opentelemetry-instrument", "python", "-m", "claims_agents.main"]
