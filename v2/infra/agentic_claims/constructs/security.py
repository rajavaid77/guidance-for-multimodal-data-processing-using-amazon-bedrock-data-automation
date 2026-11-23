"""Customer-managed KMS key and the Bedrock Guardrail applied to agent model outputs."""

from __future__ import annotations

from aws_cdk import RemovalPolicy, Stack
from aws_cdk import aws_bedrock as bedrock
from aws_cdk import aws_iam as iam
from aws_cdk import aws_kms as kms
from constructs import Construct


class Security(Construct):
    def __init__(self, scope: Construct, construct_id: str, *, prefix: str, removal: RemovalPolicy) -> None:
        super().__init__(scope, construct_id)
        stack = Stack.of(self)
        self.key = kms.Key(
            self,
            "Key",
            alias=f"alias/{prefix}",
            description="Agentic claims (v2) data key: S3, Aurora, logs, SNS, Lambda env, AgentCore memory",
            enable_key_rotation=True,
            removal_policy=removal,
        )
        self.key.add_to_resource_policy(
            iam.PolicyStatement(
                principals=[iam.ServicePrincipal(f"logs.{stack.region}.amazonaws.com")],
                actions=["kms:Encrypt*", "kms:Decrypt*", "kms:ReEncrypt*", "kms:GenerateDataKey*", "kms:Describe*"],
                resources=["*"],
                conditions={
                    "ArnLike": {
                        "kms:EncryptionContext:aws:logs:arn": f"arn:{stack.partition}:logs:{stack.region}:{stack.account}:*"
                    }
                },
            )
        )
        for service in ("events.amazonaws.com", "states.amazonaws.com"):
            self.key.add_to_resource_policy(
                iam.PolicyStatement(
                    principals=[iam.ServicePrincipal(service)],
                    actions=["kms:Decrypt", "kms:GenerateDataKey*"],
                    resources=["*"],
                    conditions={"StringEquals": {"aws:SourceAccount": stack.account}},
                )
            )

        pii_output_only = [
            bedrock.CfnGuardrail.PiiEntityConfigProperty(
                type=t,
                action="ANONYMIZE",
                input_enabled=False,
                input_action="NONE",
                output_enabled=True,
                output_action="ANONYMIZE",
            )
            for t in ("US_SOCIAL_SECURITY_NUMBER", "CREDIT_DEBIT_CARD_NUMBER", "US_BANK_ACCOUNT_NUMBER", "PASSWORD")
        ]
        self.guardrail = bedrock.CfnGuardrail(
            self,
            "Guardrail",
            name=f"{prefix}-agents",
            description="Masks financial identifiers in agent outputs and blocks prompt attacks embedded in documents",
            blocked_input_messaging="This request was blocked by the claims guardrail.",
            blocked_outputs_messaging="This response was blocked by the claims guardrail.",
            kms_key_arn=self.key.key_arn,
            sensitive_information_policy_config=bedrock.CfnGuardrail.SensitiveInformationPolicyConfigProperty(
                pii_entities_config=pii_output_only
            ),
            content_policy_config=bedrock.CfnGuardrail.ContentPolicyConfigProperty(
                filters_config=[
                    bedrock.CfnGuardrail.ContentFilterConfigProperty(
                        type="PROMPT_ATTACK", input_strength="MEDIUM", output_strength="NONE"
                    )
                ]
            ),
        )
        self.guardrail_version = bedrock.CfnGuardrailVersion(
            self,
            "GuardrailVersion",
            guardrail_identifier=self.guardrail.attr_guardrail_id,
            description="Initial version",
        )
