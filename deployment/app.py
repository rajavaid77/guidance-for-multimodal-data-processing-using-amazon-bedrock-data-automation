#!/usr/bin/env python3
# Python Built-Ins:
import json

# External Dependencies:
import aws_cdk as cdk

# Local Dependencies:
from stacks.config_utils import bool_env_var
from stacks.lending_flow_stack import LendingFlowStack
from stacks.claims_review_stack.agent import ClaimsReviewAgentStack

# Top-level configurations are loaded from environment variables at the point `cdk synth` or
# `cdk deploy` is run (or you can override here):
config = {
    "deploy_claims_review": bool_env_var("DEPLOY_CLAIMS_REVIEW", default=True),
    "deploy_lending_flow": bool_env_var("DEPLOY_LENDING_FLOW", default=True)
}
print(f"Preparing stacks with configuration:\n{json.dumps(config, indent=2)}")

app = cdk.App()

if config["deploy_lending_flow"]:
    LendingFlowStack(app, "lending-flow",
        env=cdk.Environment(
            account=app.account,  # Your AWS account ID will be picked from your CLI configuration
            region=app.region     # Your AWS region will be picked from your CLI configuration
        )
    )
else:
    print("Skipping S3 event processing stack")


if config["deploy_claims_review"]:
    # auroraPostgresStack = AuroraPostgresStack(app, "AuroraDeployStack",
    #     env=cdk.Environment(
    #         account=app.account,  # Your AWS account ID will be picked from your CLI configuration
    #         region=app.region     # Your AWS region will be picked from your CLI configuration
    #     )
    # )
    
    ClaimsReviewAgentStack(app, "claims-review",
        env=cdk.Environment(
            account=app.account,  # Your AWS account ID will be picked from your CLI configuration
            region=app.region     # Your AWS region will be picked from your CLI configuration
        )
    )
else:
    print("Skipping claims review agent stack") 


app.synth()