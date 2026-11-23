"""AgentCore: Gateway (OAuth via Cognito M2M) + Lambda tool targets, Identity credential provider, Memory, Runtime."""

from __future__ import annotations

from pathlib import Path

from aws_cdk import Annotations, Duration, RemovalPolicy, Stack
from aws_cdk import aws_bedrockagentcore as agentcore
from aws_cdk import aws_cognito as cognito
from aws_cdk import aws_ecr_assets as ecr_assets
from aws_cdk import aws_iam as iam
from aws_cdk import aws_kms as kms
from aws_cdk import aws_logs as logs
from constructs import Construct

from .database import Database
from .functions import FunctionFactory
from .knowledge import KnowledgeBase
from .security import Security
from .tool_schemas import TOOLS

AGENTS_DIR = Path(__file__).resolve().parents[3] / "agents"
MODEL_REGIONS = ("us-east-1", "us-east-2", "us-west-1", "us-west-2")
TOOL_SCOPE = "invoke"


class Agents(Construct):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        prefix: str,
        config: dict,
        security: Security,
        database: Database,
        knowledge: KnowledgeBase,
        functions: FunctionFactory,
        removal: RemovalPolicy,
    ) -> None:
        super().__init__(scope, construct_id)
        stack = Stack.of(self)
        key: kms.IKey = security.key

        # ---------- machine-to-machine OAuth for Gateway inbound auth ----------
        self.m2m_pool = cognito.UserPool(
            self,
            "M2MPool",
            user_pool_name=f"{prefix}-agent-m2m",
            self_sign_up_enabled=False,
            feature_plan=cognito.FeaturePlan.ESSENTIALS,
            password_policy=cognito.PasswordPolicy(
                min_length=14, require_digits=True, require_lowercase=True, require_uppercase=True, require_symbols=True
            ),
            removal_policy=removal,
        )
        tool_scope = cognito.ResourceServerScope(scope_name=TOOL_SCOPE, scope_description="Invoke claims tools")
        resource_server = self.m2m_pool.add_resource_server(
            "ToolsServer", identifier=f"{prefix}-tools", scopes=[tool_scope]
        )
        domain = self.m2m_pool.add_domain(
            "Domain", cognito_domain=cognito.CognitoDomainOptions(domain_prefix=f"{prefix}-m2m-{stack.account}")
        )
        self.m2m_client = self.m2m_pool.add_client(
            "AgentClient",
            generate_secret=True,
            o_auth=cognito.OAuthSettings(
                flows=cognito.OAuthFlows(client_credentials=True),
                scopes=[cognito.OAuthScope.resource_server(resource_server, tool_scope)],
            ),
            access_token_validity=Duration.minutes(60),
            prevent_user_existence_errors=True,
        )
        scope_string = f"{prefix}-tools/{TOOL_SCOPE}"

        # The key grant must exist before the Gateway is created (it encrypts data with the key at creation time),
        # so it is an inline policy on a dedicated role rather than a later DefaultPolicy statement.
        gateway_role = iam.Role(
            self,
            "GatewayRole",
            assumed_by=iam.ServicePrincipal(
                "bedrock-agentcore.amazonaws.com",
                conditions={
                    "StringEquals": {"aws:SourceAccount": stack.account},
                    "ArnLike": {
                        "aws:SourceArn": f"arn:{stack.partition}:bedrock-agentcore:{stack.region}:{stack.account}:*"
                    },
                },
            ),
            inline_policies={
                "GatewayKey": iam.PolicyDocument(
                    statements=[
                        iam.PolicyStatement(
                            actions=["kms:GenerateDataKey", "kms:Decrypt", "kms:DescribeKey"], resources=[key.key_arn]
                        )
                    ]
                )
            },
        )
        self.gateway = agentcore.Gateway(
            self,
            "Gateway",
            role=gateway_role,
            gateway_name=f"{prefix}-tools",
            description="Claims tools (codes, eligibility, duplicates, decisions) for the claims review agents",
            authorizer_configuration=agentcore.GatewayAuthorizer.using_cognito(
                user_pool=self.m2m_pool, allowed_clients=[self.m2m_client], allowed_scopes=[scope_string]
            ),
            kms_key=key,
        )

        self.tool_functions = {}
        for name, definition in TOOLS.items():
            fn = functions.create(
                self,
                f"Tool-{name}",
                handler=f"tools.{name}.handler",
                description=f"AgentCore Gateway tool: {name}",
                environment=database.data_api_env(),
            )
            database.grant_data_api(fn)
            self.gateway.add_lambda_target(
                f"Target-{name}",
                gateway_target_name=name.replace("_", "-"),
                description=definition.description[:200],
                lambda_function=fn,
                tool_schema=agentcore.ToolSchema.from_inline([definition]),
            )
            self.tool_functions[name] = fn

        # ---------- AgentCore Identity: token vault entry the runtime uses to get Gateway tokens ----------
        self.oauth_provider = agentcore.OAuth2CredentialProvider.using_cognito(
            self,
            "GatewayOAuth",
            o_auth2_credential_provider_name=f"{prefix}-gateway-oauth",
            client_id=self.m2m_client.user_pool_client_id,
            client_secret=self.m2m_client.user_pool_client_secret,
            issuer=f"https://cognito-idp.{stack.region}.amazonaws.com/{self.m2m_pool.user_pool_id}",
            token_endpoint=f"{domain.base_url()}/oauth2/token",
            authorization_endpoint=f"{domain.base_url()}/oauth2/authorize",
        )

        Annotations.of(self.oauth_provider).acknowledge_warning(
            "aws-cdk-lib.aws-bedrockagentcore:wildcardSecretArnGrant",
            "Token vault secret ARN is generated by the service; grant is scoped to the bedrock-agentcore-identity! prefix",
        )

        # ---------- Memory (short-term, per claim session) ----------
        self.memory = agentcore.Memory(
            self,
            "Memory",
            memory_name=f"{prefix.replace('-', '_')}_review_memory",
            description="Claim review session context for the supervisor agent",
            expiration_duration=Duration.days(30),
            kms_key=key,
        )

        # ---------- Runtime ----------
        runtime_logs = logs.LogGroup(
            self,
            "RuntimeLogs",
            log_group_name=f"/aws/vendedlogs/bedrock-agentcore/{prefix}-runtime",
            retention=logs.RetentionDays.ONE_MONTH,
            encryption_key=key,
            removal_policy=removal,
        )
        self.runtime = agentcore.Runtime(
            self,
            "Runtime",
            runtime_name=f"{prefix.replace('-', '_')}_reviewer",
            description="Strands multi-agent CMS-1500 claims reviewer",
            agent_runtime_artifact=agentcore.AgentRuntimeArtifact.from_asset(
                str(AGENTS_DIR), platform=ecr_assets.Platform.LINUX_ARM64, exclude=[".venv", "tests", "**/__pycache__"]
            ),
            environment_variables={
                "REASONING_MODEL_ID": config["reasoning_model_id"],
                "FAST_MODEL_ID": config["fast_model_id"],
                "GUARDRAIL_ID": security.guardrail.attr_guardrail_id,
                "GUARDRAIL_VERSION": security.guardrail_version.attr_version,
                "KNOWLEDGE_BASE_ID": knowledge.kb.attr_knowledge_base_id,
                "MEMORY_ID": self.memory.memory_id,
                "GATEWAY_URL": self.gateway.gateway_url,
                "GATEWAY_OAUTH_PROVIDER_NAME": self.oauth_provider.o_auth2_credential_provider_name,
                "GATEWAY_OAUTH_SCOPES": scope_string,
                "PROMPT_VERSION": config.get("prompt_version", "1"),
                "AGENT_OBSERVABILITY_ENABLED": "true",
                "OTEL_PYTHON_DISTRO": "aws_distro",
                "OTEL_PYTHON_CONFIGURATOR": "aws_configurator",
            },
            lifecycle_configuration=agentcore.LifecycleConfiguration(
                idle_runtime_session_timeout=Duration.minutes(15), max_lifetime=Duration.hours(1)
            ),
            tracing_enabled=True,
            logging_configs=[
                agentcore.LoggingConfig(
                    log_type=agentcore.LogType.APPLICATION_LOGS,
                    destination=agentcore.LoggingDestination.cloud_watch_logs(runtime_logs),
                )
            ],
        )
        role = self.runtime.role
        self.oauth_provider.grant_use(self.runtime)
        self.memory.grant_read_short_term_memory(self.runtime)
        self.memory.grant_write(self.runtime)
        knowledge.grant_retrieve(self.runtime)
        key.grant_decrypt(role)

        models = [config["reasoning_model_id"], config["fast_model_id"]]
        base_models = [m.split(".", 1)[1] if m.split(".", 1)[0] in ("us", "global") else m for m in models]
        self.runtime.add_to_role_policy(
            iam.PolicyStatement(
                actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
                resources=[
                    *[
                        f"arn:{stack.partition}:bedrock:{stack.region}:{stack.account}:inference-profile/{m}"
                        for m in models
                    ],
                    *[
                        f"arn:{stack.partition}:bedrock:{r}::foundation-model/{b}*"
                        for r in MODEL_REGIONS
                        for b in base_models
                    ],
                    f"arn:{stack.partition}:bedrock:::foundation-model/{base_models[0]}*",
                    f"arn:{stack.partition}:bedrock:::foundation-model/{base_models[1]}*",
                ],
            )
        )
        self.runtime.add_to_role_policy(
            iam.PolicyStatement(actions=["bedrock:ApplyGuardrail"], resources=[security.guardrail.attr_guardrail_arn])
        )
