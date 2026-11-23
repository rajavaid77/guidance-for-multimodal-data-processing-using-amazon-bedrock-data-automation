"""REST API for the Provider Portal and Examiner UI. Every method requires a Cognito ID token."""

from __future__ import annotations

from aws_cdk import Duration, RemovalPolicy
from aws_cdk import aws_apigateway as apigw
from aws_cdk import aws_cognito as cognito
from aws_cdk import aws_kms as kms
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_wafv2 as wafv2
from constructs import Construct

from .database import Database
from .functions import FunctionFactory


class ClaimsApi(Construct):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        prefix: str,
        user_pool: cognito.IUserPool,
        intake: s3.IBucket,
        database: Database,
        functions: FunctionFactory,
        state_machine_arn_grant,
        key: kms.IKey,
        app_origin: str,
        enable_waf: bool,
        removal: RemovalPolicy,
    ) -> None:
        super().__init__(scope, construct_id)
        env = {**database.data_api_env(), "INTAKE_BUCKET": intake.bucket_name, "ALLOWED_ORIGIN": app_origin}

        provider_fn = functions.create(
            self,
            "ProviderClaims",
            handler="api.provider_claims.handler",
            description="Provider Portal claim API",
            environment=env,
        )
        examiner_fn = functions.create(
            self,
            "ExaminerReviews",
            handler="api.examiner_reviews.handler",
            description="Examiner review API",
            environment=env,
        )
        self.provider_fn, self.examiner_fn = provider_fn, examiner_fn
        for f in (provider_fn, examiner_fn):
            database.grant_data_api(f)
        intake.grant_put(provider_fn)
        intake.grant_read(provider_fn)
        intake.grant_read(examiner_fn)
        key.grant_encrypt_decrypt(provider_fn)
        key.grant_encrypt_decrypt(examiner_fn)  # SendTaskSuccess output is encrypted with the CMK
        state_machine_arn_grant(examiner_fn)

        access_logs = logs.LogGroup(
            self, "AccessLogs", retention=logs.RetentionDays.ONE_MONTH, encryption_key=key, removal_policy=removal
        )
        authorizer = apigw.CognitoUserPoolsAuthorizer(self, "Authorizer", cognito_user_pools=[user_pool])
        cors = apigw.CorsOptions(
            allow_origins=[app_origin],
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type"],
            max_age=Duration.minutes(10),
        )
        self.api = apigw.RestApi(
            self,
            "Api",
            rest_api_name=f"{prefix}-api",
            description="Agentic claims provider and examiner API",
            endpoint_types=[apigw.EndpointType.REGIONAL],
            cloud_watch_role=False,
            default_cors_preflight_options=cors,
            default_method_options=apigw.MethodOptions(
                authorizer=authorizer, authorization_type=apigw.AuthorizationType.COGNITO
            ),
            deploy_options=apigw.StageOptions(
                stage_name="v1",
                tracing_enabled=True,
                throttling_rate_limit=20,
                throttling_burst_limit=40,
                logging_level=apigw.MethodLoggingLevel.OFF,
                data_trace_enabled=False,
                access_log_destination=apigw.LogGroupLogDestination(access_logs),
                access_log_format=apigw.AccessLogFormat.json_with_standard_fields(
                    caller=False,
                    http_method=True,
                    ip=True,
                    protocol=True,
                    request_time=True,
                    resource_path=True,
                    response_length=True,
                    status=True,
                    user=True,
                ),
            ),
        )
        # CORS headers on gateway-generated errors (401/403/429/5xx) so the browser can read them.
        for rtype in (apigw.ResponseType.DEFAULT_4_XX, apigw.ResponseType.DEFAULT_5_XX):
            self.api.add_gateway_response(
                f"Cors{rtype.response_type}",
                type=rtype,
                response_headers={"Access-Control-Allow-Origin": f"'{app_origin}'"},
            )

        validator = self.api.add_request_validator(
            "Validator", validate_request_body=True, validate_request_parameters=True
        )
        self._method_opts = {"request_validator": validator}
        p = apigw.LambdaIntegration(provider_fn)
        e = apigw.LambdaIntegration(examiner_fn)
        claims = self.api.root.add_resource("claims")
        claims.add_method("GET", p, **self._method_opts)
        claims.add_method("POST", p, **self._method_opts)
        claim = claims.add_resource("{claimId}")
        claim.add_method("GET", p, **self._method_opts)
        claim.add_resource("submit").add_method("POST", p, **self._method_opts)
        reviews = self.api.root.add_resource("reviews")
        reviews.add_method("GET", e, **self._method_opts)
        review = reviews.add_resource("{claimId}")
        review.add_method("GET", e, **self._method_opts)
        review.add_resource("decision").add_method("POST", e, **self._method_opts)

        if enable_waf:
            acl = wafv2.CfnWebACL(
                self,
                "WebAcl",
                scope="REGIONAL",
                default_action=wafv2.CfnWebACL.DefaultActionProperty(allow={}),
                visibility_config=wafv2.CfnWebACL.VisibilityConfigProperty(
                    cloud_watch_metrics_enabled=True, metric_name=f"{prefix}-api", sampled_requests_enabled=True
                ),
                rules=[
                    self._managed_rule("AWSManagedRulesCommonRuleSet", 1, prefix),
                    self._managed_rule("AWSManagedRulesKnownBadInputsRuleSet", 2, prefix),
                    wafv2.CfnWebACL.RuleProperty(
                        name="RateLimit",
                        priority=3,
                        action=wafv2.CfnWebACL.RuleActionProperty(block={}),
                        statement=wafv2.CfnWebACL.StatementProperty(
                            rate_based_statement=wafv2.CfnWebACL.RateBasedStatementProperty(
                                limit=1000, aggregate_key_type="IP"
                            )
                        ),
                        visibility_config=wafv2.CfnWebACL.VisibilityConfigProperty(
                            cloud_watch_metrics_enabled=True,
                            metric_name=f"{prefix}-rate",
                            sampled_requests_enabled=True,
                        ),
                    ),
                ],
            )
            wafv2.CfnWebACLAssociation(
                self, "WebAclAssociation", resource_arn=self.api.deployment_stage.stage_arn, web_acl_arn=acl.attr_arn
            )

    @staticmethod
    def _managed_rule(name: str, priority: int, prefix: str):
        return wafv2.CfnWebACL.RuleProperty(
            name=name,
            priority=priority,
            override_action=wafv2.CfnWebACL.OverrideActionProperty(none={}),
            statement=wafv2.CfnWebACL.StatementProperty(
                managed_rule_group_statement=wafv2.CfnWebACL.ManagedRuleGroupStatementProperty(
                    vendor_name="AWS", name=name
                )
            ),
            visibility_config=wafv2.CfnWebACL.VisibilityConfigProperty(
                cloud_watch_metrics_enabled=True, metric_name=f"{prefix}-{name}", sampled_requests_enabled=True
            ),
        )
