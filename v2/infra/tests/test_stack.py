"""Synthesizes the stack and asserts the security-critical properties."""

import json
from pathlib import Path

import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Match, Template

from agentic_claims.stack import AgenticClaimsStack

CONTEXT = json.loads((Path(__file__).resolve().parents[1] / "cdk.json").read_text())["context"]
CONFIG = CONTEXT["agentic_claims"]


@pytest.fixture(scope="module")
def template() -> Template:
    app = cdk.App(context={**CONTEXT, "nag": "off"})
    stack = AgenticClaimsStack(
        app, "test", config=CONFIG, env=cdk.Environment(account="111111111111", region="us-west-2")
    )
    return Template.from_stack(stack)


def test_every_api_method_requires_cognito_except_preflight(template):
    methods = template.find_resources("AWS::ApiGateway::Method")
    assert methods
    for name, m in methods.items():
        props = m["Properties"]
        if props["HttpMethod"] == "OPTIONS":
            assert props["AuthorizationType"] == "NONE"
        else:
            assert props["AuthorizationType"] == "COGNITO_USER_POOLS", name


def test_database_is_private_and_encrypted(template):
    template.has_resource_properties("AWS::RDS::DBInstance", {"PubliclyAccessible": False})
    template.has_resource_properties(
        "AWS::RDS::DBCluster", {"StorageEncrypted": True, "EnableHttpEndpoint": True, "KmsKeyId": Match.any_value()}
    )
    for sg in template.find_resources("AWS::EC2::SecurityGroup").values():
        assert not sg["Properties"].get("SecurityGroupIngress"), "no ingress expected"


def test_buckets_block_public_access_and_require_tls(template):
    buckets = template.find_resources("AWS::S3::Bucket")
    for name, b in buckets.items():
        assert b["Properties"]["PublicAccessBlockConfiguration"] == {
            "BlockPublicAcls": True,
            "BlockPublicPolicy": True,
            "IgnorePublicAcls": True,
            "RestrictPublicBuckets": True,
        }, name
    policies = json.dumps(template.find_resources("AWS::S3::BucketPolicy"))
    assert '"aws:SecureTransport": "false"' in policies


def test_vpc_has_no_internet_path(template):
    template.resource_count_is("AWS::EC2::NatGateway", 0)
    template.resource_count_is("AWS::EC2::InternetGateway", 0)


def test_user_pool_has_no_self_signup_and_requires_mfa(template):
    template.has_resource_properties(
        "AWS::Cognito::UserPool",
        {
            "UserPoolName": "agentic-claims-users",
            "MfaConfiguration": "ON",
            "AdminCreateUserConfig": {"AllowAdminCreateUserOnly": True},
        },
    )
    # Web client cannot write custom:provider_id (would allow cross-provider access)
    clients = template.find_resources(
        "AWS::Cognito::UserPoolClient", {"Properties": {"ClientName": "agentic-claims-web"}}
    )
    (client,) = clients.values()
    assert "custom:provider_id" not in client["Properties"]["WriteAttributes"]


def test_gateway_uses_oauth_jwt_and_runtime_exists(template):
    template.has_resource_properties("AWS::BedrockAgentCore::Gateway", {"AuthorizerType": "CUSTOM_JWT"})
    template.resource_count_is("AWS::BedrockAgentCore::GatewayTarget", 4)
    template.resource_count_is("AWS::BedrockAgentCore::Runtime", 1)
    template.resource_count_is("AWS::BedrockAgentCore::OAuth2CredentialProvider", 1)
    template.resource_count_is("AWS::BedrockAgentCore::Memory", 1)


def test_knowledge_base_uses_s3_vectors(template):
    template.has_resource_properties(
        "AWS::Bedrock::KnowledgeBase",
        {"StorageConfiguration": {"Type": "S3_VECTORS", "S3VectorsConfiguration": Match.any_value()}},
    )


def test_state_machine_does_not_log_execution_data(template):
    template.has_resource_properties(
        "AWS::StepFunctions::StateMachine",
        {"LoggingConfiguration": Match.object_like({"IncludeExecutionData": False, "Level": "ERROR"})},
    )
