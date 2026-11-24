"""Shared Lambda function factory: Python 3.13 on ARM64, X-Ray, KMS-encrypted env, retained logs, fresh boto3 layer."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from aws_cdk import Duration, RemovalPolicy
from aws_cdk import aws_kms as kms
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from constructs import Construct

ROOT = Path(__file__).resolve().parents[2]
LAMBDA_SRC = str(ROOT / "lambdas")
LAYER_REQ = ROOT / "layers" / "boto3" / "requirements.txt"
LAYER_BUILD = ROOT / "layers" / "boto3" / ".build"


def build_boto3_layer() -> str:
    """boto3 is pure Python, so the layer is built locally (no Docker) once per requirements change."""
    marker = LAYER_BUILD / ".requirements"
    if marker.exists() and marker.read_text() == LAYER_REQ.read_text():
        return str(LAYER_BUILD)
    shutil.rmtree(LAYER_BUILD, ignore_errors=True)
    target = LAYER_BUILD / "python"
    # boto3/botocore are pure Python wheels, so no platform-specific build is needed.
    args = ["install", "-r", str(LAYER_REQ), "--target", str(target), "--quiet"]
    uv = shutil.which("uv")
    # Argument lists are fixed at build time: the interpreter path, a PATH-resolved uv, and module-level
    # constant paths. shell=False (list form), so no shell parsing or injection is possible.
    if uv:
        subprocess.run([uv, "pip", *args, "--python", sys.executable], check=True)  # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit
    else:
        subprocess.run([sys.executable, "-m", "pip", *args, "--no-cache-dir"], check=True)  # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit
    marker.write_text(LAYER_REQ.read_text())
    return str(LAYER_BUILD)


class FunctionFactory(Construct):
    def __init__(self, scope: Construct, construct_id: str, *, key: kms.IKey, removal: RemovalPolicy) -> None:
        super().__init__(scope, construct_id)
        self._key = key
        self._removal = removal
        self._code = lambda_.Code.from_asset(LAMBDA_SRC, exclude=["**/__pycache__", "tests"])
        self.layer = lambda_.LayerVersion(
            self,
            "Boto3Layer",
            code=lambda_.Code.from_asset(build_boto3_layer(), exclude=[".requirements"]),
            compatible_runtimes=[lambda_.Runtime.PYTHON_3_13],
            compatible_architectures=[lambda_.Architecture.ARM_64],
            description="Recent boto3 for bedrock-data-automation-runtime and bedrock-agentcore APIs",
        )

    def create(
        self,
        scope: Construct,
        construct_id: str,
        *,
        handler: str,
        description: str,
        environment: dict[str, str] | None = None,
        timeout: Duration | None = None,
        memory_size: int = 256,
    ) -> lambda_.Function:
        log_group = logs.LogGroup(
            scope,
            f"{construct_id}Logs",
            retention=logs.RetentionDays.ONE_MONTH,
            encryption_key=self._key,
            removal_policy=self._removal,
        )
        return lambda_.Function(
            scope,
            construct_id,
            runtime=lambda_.Runtime.PYTHON_3_13,
            architecture=lambda_.Architecture.ARM_64,
            handler=handler,
            code=self._code,
            layers=[self.layer],
            description=description,
            environment={"POWERTOOLS_SERVICE_NAME": "agentic-claims", **(environment or {})},
            environment_encryption=self._key,
            timeout=timeout or Duration.seconds(30),
            memory_size=memory_size,
            tracing=lambda_.Tracing.ACTIVE,
            log_group=log_group,
        )
