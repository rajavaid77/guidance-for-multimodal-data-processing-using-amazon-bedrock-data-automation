"""Amplify Hosting app for the Provider Portal + Examiner UI (single React SPA, role-based areas)."""

from __future__ import annotations

from pathlib import Path

from aws_cdk import CustomResource, Duration, Stack
from aws_cdk import aws_amplify_alpha as amplify
from aws_cdk import aws_iam as iam
from aws_cdk import aws_s3_assets as s3_assets
from aws_cdk import custom_resources as cr
from constructs import Construct

from .functions import FunctionFactory

WEB_DIST = Path(__file__).resolve().parents[3] / "web" / "dist"
BRANCH = "main"

SECURITY_HEADERS = {
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}


class WebApp(Construct):
    """Created in two steps so the API can use the app origin before the site content is deployed."""

    def __init__(self, scope: Construct, construct_id: str, *, prefix: str) -> None:
        super().__init__(scope, construct_id)
        self.app = amplify.App(
            self,
            "App",
            app_name=f"{prefix}-portal",
            description="Provider Portal and Examiner UI",
            custom_rules=[amplify.CustomRule.SINGLE_PAGE_APPLICATION_REDIRECT],
            custom_response_headers=[amplify.CustomResponseHeader(pattern="**", headers=SECURITY_HEADERS)],
        )
        self.branch = self.app.add_branch("Main", branch_name=BRANCH, stage="PRODUCTION", auto_build=False)
        self.origin = f"https://{BRANCH}.{self.app.default_domain}"

    def deploy(self, *, functions: FunctionFactory, site_config: dict[str, str]) -> None:
        if not (WEB_DIST / "index.html").exists():
            raise FileNotFoundError(f"Build the web app first: (cd v2/web && npm ci && npm run build) -> {WEB_DIST}")
        stack = Stack.of(self)
        asset = s3_assets.Asset(self, "Dist", path=str(WEB_DIST))
        deploy_fn = functions.create(
            self,
            "DeployFn",
            handler="custom_resources.amplify_deploy.handler",
            description="Deploys the built SPA with config.json to Amplify Hosting",
            timeout=Duration.minutes(14),
            memory_size=512,
        )
        asset.grant_read(deploy_fn)
        deploy_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["amplify:CreateDeployment", "amplify:StartDeployment", "amplify:GetJob"],
                resources=[
                    f"arn:{stack.partition}:amplify:{stack.region}:{stack.account}:apps/{self.app.app_id}/branches/{BRANCH}",
                    f"arn:{stack.partition}:amplify:{stack.region}:{stack.account}:apps/{self.app.app_id}/branches/{BRANCH}/jobs/*",
                    f"arn:{stack.partition}:amplify:{stack.region}:{stack.account}:apps/{self.app.app_id}/branches/{BRANCH}/deployments/*",
                ],
            )
        )
        provider = cr.Provider(self, "DeployProvider", on_event_handler=deploy_fn)
        resource = CustomResource(
            self,
            "Deployment",
            service_token=provider.service_token,
            properties={
                "AppId": self.app.app_id,
                "BranchName": BRANCH,
                "AssetBucket": asset.s3_bucket_name,
                "AssetKey": asset.s3_object_key,
                "Config": stack.to_json_string(site_config),
            },
        )
        resource.node.add_dependency(self.branch)
