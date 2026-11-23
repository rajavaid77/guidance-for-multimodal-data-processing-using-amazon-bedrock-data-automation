"""cdk-nag acknowledgements. Each states why a finding does not apply or is an accepted trade-off for this guidance.

Review these before production use; several are reasonable defaults for a sample but should be revisited
(secret rotation, WAF logging, cross-region replication, AWS Backup plans).
"""

from __future__ import annotations

from aws_cdk import Acknowledgment, CfnResource, Stack, Validations

ACKNOWLEDGEMENTS: dict[str, str] = {
    # ---- IAM ----
    "HIPAA.Security-IAMNoInlinePolicy": "CDK grant helpers attach least-privilege inline policies to each role.",
    # ---- Lambda ----
    "HIPAA.Security-LambdaInsideVPC": (
        "Functions reach Aurora only through the RDS Data API (IAM-authorized HTTPS) and call regional AWS APIs; "
        "the VPC has isolated subnets with no NAT, so VPC attachment would add endpoints without reducing exposure."
    ),
    "HIPAA.Security-LambdaDLQ": (
        "Functions are invoked synchronously by Step Functions/API Gateway (errors surface to the caller and the "
        "workflow catch); asynchronous EventBridge targets have an SQS dead-letter queue."
    ),
    "HIPAA.Security-LambdaConcurrency": "Throughput is bounded by API Gateway throttling and Step Functions; set per workload.",
    "AwsSolutions-L1": "Custom resource provider frameworks managed by CDK pin their own runtime versions.",
    # ---- Logging / storage ----
    "HIPAA.Security-CloudWatchLogGroupEncrypted": (
        "Remaining unencrypted log groups belong to CDK-managed custom resource providers and Aurora log exports "
        "that contain no claim data; application log groups use the customer managed key."
    ),
    "HIPAA.Security-S3DefaultEncryptionKMS": "The server access log bucket must use SSE-S3 (S3 log delivery does not support SSE-KMS).",
    "HIPAA.Security-S3BucketReplicationEnabled": "Cross-region replication is a deployment choice; enable per DR requirements.",
    "AwsSolutions-SQS3": "This queue is itself the dead-letter queue for EventBridge targets.",
    "AwsSolutions-SF1": (
        "Step Functions logs at ERROR level with execution data excluded so claim PHI never lands in logs; "
        "per-claim history is kept in the audit_events table."
    ),
    "HIPAA.Security-WAFv2LoggingEnabled": "Enable WAF logging to a KMS-encrypted destination per your SIEM setup.",
    # ---- Database ----
    "AwsSolutions-RDS10": "Deletion protection follows the removal_policy context value (retain => protected).",
    "HIPAA.Security-RDSInstanceDeletionProtectionEnabled": "Deletion protection follows the removal_policy context value.",
    "HIPAA.Security-RDSInBackupPlan": "Aurora automated backups (7 days) are enabled; add AWS Backup plans for long-term retention.",
    "AwsSolutions-SMG4": (
        "The admin secret is only used by the RDS Data API from IAM-authorized callers; enable rotation (requires a "
        "Secrets Manager VPC endpoint in the isolated subnets) for production."
    ),
    "HIPAA.Security-SecretsManagerRotationEnabled": "See AwsSolutions-SMG4.",
    # ---- API Gateway / Cognito ----
    "HIPAA.Security-APIGWSSLEnabled": "Backends are Lambda proxy integrations; client certificates apply to HTTP backends only.",
    "HIPAA.Security-APIGWExecutionLoggingEnabled": (
        "Access logging is enabled; execution logging needs an account-level CloudWatch role and could capture PHI."
    ),
    "AwsSolutions-APIG6": "See HIPAA.Security-APIGWExecutionLoggingEnabled; access logs are enabled.",
    "HIPAA.Security-APIGWCacheEnabledAndEncrypted": "Responses contain per-user PHI and must not be cached.",
    "AwsSolutions-COG2": "MFA is required for the human user pool; the machine-to-machine pool only issues client_credentials tokens.",
    "AwsSolutions-COG8": "The Plus feature plan is used for the human user pool; the M2M pool has no end users.",
    "AwsSolutions-COG3": "Threat protection is enabled on the human user pool; the M2M pool has no end users.",
}


IAM4_REASON = "AWSLambdaBasicExecutionRole is the CDK default for writing function logs."
IAM5_REASON = (
    "Scoped wildcard from a CDK grant helper or a service-generated ARN: object keys within this stack's buckets, "
    "KMS key actions on this stack's key, Lambda versions/aliases, BDA invocations, AgentCore runtime log groups, "
    "token-vault secrets and workload identities, Amplify jobs, and model families across the US cross-region "
    "inference profile regions. Resource '*' is only used for X-Ray, CloudWatch metrics, ECR auth and log delivery, "
    "which do not support resource-level permissions."
)
GRANT_ACTIONS = (
    "s3:List*",
    "s3:GetObject*",
    "s3:GetBucket*",
    "s3:Abort*",
    "s3:DeleteObject*",
    "kms:ReEncrypt*",
    "kms:GenerateDataKey*",
    "s3:PutObject*",
    "bedrock-agentcore:*",
)


def _iam5_findings(stack: Stack, config: dict) -> list[str]:
    acct, region = stack.account, stack.region
    findings = [f"Action::{a}" for a in GRANT_ACTIONS] + [
        "Resource::*",
        f"Resource::arn:aws:s3:::cdk-hnb659fds-assets-{acct}-{region}/*",
        f"Resource::arn:aws:secretsmanager:{region}:{acct}:secret:bedrock-agentcore-identity!*",
        f"Resource::arn:aws:logs:{region}:{acct}:log-group:/aws/bedrock-agentcore/runtimes/*",
        f"Resource::arn:aws:logs:{region}:{acct}:log-group:/aws/bedrock-agentcore/runtimes/*:log-stream:*",
        f"Resource::arn:aws:logs:{region}:{acct}:log-group:*",
        f"Resource::arn:aws:bedrock:{region}:{acct}:data-automation-invocation/*",
        f"Resource::arn:aws:bedrock-agentcore:{region}:{acct}:workload-identity-directory/default/workload-identity/*",
    ]
    for model in (config["reasoning_model_id"], config["fast_model_id"]):
        base = model.split(".", 1)[1] if model.split(".", 1)[0] in ("us", "global") else model
        findings.append(f"Resource::arn:aws:bedrock:::foundation-model/{base}*")
        for r in ("us-east-1", "us-east-2", "us-west-1", "us-west-2"):
            findings.append(f"Resource::arn:aws:bedrock:{r}::foundation-model/{base}*")
    for node in stack.node.find_all():
        if isinstance(node, CfnResource):
            lid = stack.resolve(stack.get_logical_id(node))
            findings += [f"Resource::<{lid}.Arn>/*", f"Resource::<{lid}.Arn>:*", f"Resource::<{lid}.AgentRuntimeArn>/*"]
            if node.cfn_resource_type == "AWS::Amplify::App":
                findings.append(f"Resource::arn:aws:amplify:{region}:{acct}:apps/<{lid}.AppId>/branches/main/jobs/*")
                findings.append(
                    f"Resource::arn:aws:amplify:{region}:{acct}:apps/<{lid}.AppId>/branches/main/deployments/*"
                )
    return findings


def _qualified(rule_id: str) -> str:
    pack = rule_id.split("-", 1)[0]  # "AwsSolutions" or "HIPAA.Security"
    return f"{pack}::{rule_id}"


def apply_suppressions(stack: Stack, config: dict) -> None:
    acks = [Acknowledgment(id=_qualified(rule_id), reason=reason) for rule_id, reason in ACKNOWLEDGEMENTS.items()]
    acks.append(
        Acknowledgment(
            id="AwsSolutions::AwsSolutions-IAM4[Policy::arn:<AWS::Partition>:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole]",
            reason=IAM4_REASON,
        )
    )
    acks.append(
        Acknowledgment(
            id="AwsSolutions::AwsSolutions-IAM4[Policy::arn:<AWS::Partition>:iam::aws:policy/service-role/AmazonRDSEnhancedMonitoringRole]",
            reason="AWS managed role policy required by RDS Enhanced Monitoring.",
        )
    )
    acks += [
        Acknowledgment(id=f"AwsSolutions::AwsSolutions-IAM5[{f}]", reason=IAM5_REASON)
        for f in _iam5_findings(stack, config)
    ]
    Validations.of(stack).acknowledge(*acks)
