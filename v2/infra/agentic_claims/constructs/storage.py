"""S3 buckets: private, KMS-encrypted, TLS-only, versioned, with server access logging."""

from __future__ import annotations

from aws_cdk import Duration, RemovalPolicy
from aws_cdk import aws_kms as kms
from aws_cdk import aws_s3 as s3
from constructs import Construct


class Storage(Construct):
    def __init__(
        self, scope: Construct, construct_id: str, *, key: kms.IKey, removal: RemovalPolicy, app_origin: str
    ) -> None:
        super().__init__(scope, construct_id)
        auto_delete = removal == RemovalPolicy.DESTROY
        self.access_logs = s3.Bucket(
            self,
            "AccessLogs",
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            versioned=True,
            object_ownership=s3.ObjectOwnership.BUCKET_OWNER_ENFORCED,
            lifecycle_rules=[s3.LifecycleRule(expiration=Duration.days(365))],
            removal_policy=removal,
            auto_delete_objects=auto_delete,
        )

        def bucket(name: str, **kwargs) -> s3.Bucket:
            return s3.Bucket(
                self,
                name,
                encryption=s3.BucketEncryption.KMS,
                encryption_key=key,
                bucket_key_enabled=True,
                block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
                enforce_ssl=True,
                versioned=True,
                object_ownership=s3.ObjectOwnership.BUCKET_OWNER_ENFORCED,
                server_access_logs_bucket=self.access_logs,
                server_access_logs_prefix=f"{name.lower()}/",
                removal_policy=removal,
                auto_delete_objects=auto_delete,
                **kwargs,
            )

        # Browser uploads/downloads use short-lived pre-signed URLs; CORS only for the Amplify app origin.
        self.intake = bucket(
            "Intake",
            event_bridge_enabled=True,
            cors=[
                s3.CorsRule(
                    allowed_methods=[s3.HttpMethods.PUT, s3.HttpMethods.GET],
                    allowed_origins=[app_origin],
                    allowed_headers=["content-type"],
                    max_age=300,
                )
            ],
        )
        self.bda_output = bucket("BdaOutput")
        self.policy_docs = bucket("PolicyDocs")
