#!/usr/bin/env python3
"""CDK app for the agentic CMS-1500 claims processing guidance (v2)."""

import os

import aws_cdk as cdk
from cdk_nag import AwsSolutionsChecks, HIPAASecurityChecks

from agentic_claims.stack import AgenticClaimsStack

app = cdk.App()
cfg = app.node.try_get_context("agentic_claims")

AgenticClaimsStack(
    app,
    cfg["stack_name"],
    config=cfg,
    description="Guidance for agentic CMS-1500 claims processing with Amazon Bedrock Data Automation and AgentCore (v2)",
    env=cdk.Environment(
        account=os.environ.get("CDK_DEFAULT_ACCOUNT"), region=cfg.get("region") or os.environ.get("CDK_DEFAULT_REGION")
    ),
)

if app.node.try_get_context("nag") != "off":
    cdk.Validations.of(app).add_plugins(AwsSolutionsChecks(app), HIPAASecurityChecks(app))

app.synth()
