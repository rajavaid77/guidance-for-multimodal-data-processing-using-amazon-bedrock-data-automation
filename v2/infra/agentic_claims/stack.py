"""Agentic CMS-1500 claims processing stack (v2)."""

from __future__ import annotations

from aws_cdk import CfnOutput, RemovalPolicy, Stack
from constructs import Construct

from .constructs.agents import Agents
from .constructs.api import ClaimsApi
from .constructs.auth import UserAuth
from .constructs.database import Database
from .constructs.functions import FunctionFactory
from .constructs.idp import DocumentAutomation
from .constructs.knowledge import KnowledgeBase
from .constructs.network import Network
from .constructs.security import Security
from .constructs.storage import Storage
from .constructs.web import WebApp
from .constructs.workflow import Workflow
from .nag import apply_suppressions


class AgenticClaimsStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, *, config: dict, **kwargs) -> None:
        self._azs = list(config["availability_zones"])
        super().__init__(scope, construct_id, **kwargs)
        prefix = config["resource_prefix"]
        removal = RemovalPolicy.RETAIN if config.get("removal_policy") == "retain" else RemovalPolicy.DESTROY

        security = Security(self, "Security", prefix=prefix, removal=removal)
        key = security.key
        functions = FunctionFactory(self, "Functions", key=key, removal=removal)
        network = Network(
            self, "Network", key=key, removal=removal, availability_zones=list(config["availability_zones"])
        )
        web = WebApp(self, "Web", prefix=prefix)
        storage = Storage(self, "Storage", key=key, removal=removal, app_origin=web.origin)
        database = Database(self, "Database", vpc=network.vpc, key=key, functions=functions, removal=removal)
        idp = DocumentAutomation(self, "DocumentAutomation", prefix=prefix, key=key, profile=config["bda_profile"])
        knowledge = KnowledgeBase(
            self,
            "Knowledge",
            prefix=prefix,
            policy_bucket=storage.policy_docs,
            key=key,
            embedding_model_id=config["embedding_model_id"],
            dimensions=int(config["embedding_dimensions"]),
        )
        agents = Agents(
            self,
            "Agents",
            prefix=prefix,
            config=config,
            security=security,
            database=database,
            knowledge=knowledge,
            functions=functions,
            removal=removal,
        )
        workflow = Workflow(
            self,
            "Workflow",
            config=config,
            key=key,
            intake=storage.intake,
            bda_output=storage.bda_output,
            database=database,
            idp=idp,
            agents=agents,
            functions=functions,
            app_url=web.origin,
            removal=removal,
        )
        auth = UserAuth(self, "Auth", prefix=prefix, removal=removal)
        api = ClaimsApi(
            self,
            "Api",
            prefix=prefix,
            user_pool=auth.user_pool,
            intake=storage.intake,
            database=database,
            functions=functions,
            state_machine_arn_grant=workflow.state_machine.grant_task_response,
            key=key,
            app_origin=web.origin,
            enable_waf=bool(config.get("enable_waf", True)),
            removal=removal,
        )
        web.deploy(
            functions=functions,
            site_config={
                "region": self.region,
                "userPoolId": auth.user_pool.user_pool_id,
                "userPoolClientId": auth.web_client.user_pool_client_id,
                "apiUrl": api.api.url,
            },
        )

        CfnOutput(self, "AppUrl", value=web.origin)
        CfnOutput(self, "ApiUrl", value=api.api.url)
        CfnOutput(self, "UserPoolId", value=auth.user_pool.user_pool_id)
        CfnOutput(self, "IntakeBucket", value=storage.intake.bucket_name)
        CfnOutput(self, "StateMachineArn", value=workflow.state_machine.state_machine_arn)
        CfnOutput(self, "AgentRuntimeArn", value=agents.runtime.agent_runtime_arn)
        CfnOutput(self, "GatewayUrl", value=agents.gateway.gateway_url)
        CfnOutput(self, "KnowledgeBaseId", value=knowledge.kb.attr_knowledge_base_id)
        CfnOutput(self, "DataSourceId", value=knowledge.data_source.attr_data_source_id)
        CfnOutput(self, "ReviewTopicArn", value=workflow.topic.topic_arn)
        CfnOutput(self, "PolicyBucket", value=storage.policy_docs.bucket_name)
        CfnOutput(self, "ProviderApiFunction", value=api.provider_fn.function_name)
        CfnOutput(self, "ExaminerApiFunction", value=api.examiner_fn.function_name)

        apply_suppressions(self, config)

    @property
    def availability_zones(self) -> list[str]:
        """Pinned in cdk.json so synth needs no account lookup."""
        return self._azs
