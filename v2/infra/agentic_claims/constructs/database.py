"""Aurora PostgreSQL Serverless v2 in isolated subnets, accessed only through the RDS Data API (IAM-authorized)."""

from __future__ import annotations

import hashlib
from pathlib import Path

from aws_cdk import CustomResource, Duration, RemovalPolicy
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_kms as kms
from aws_cdk import aws_logs as logs
from aws_cdk import aws_rds as rds
from aws_cdk import aws_s3_assets as s3_assets
from aws_cdk import custom_resources as cr
from constructs import Construct

from .functions import FunctionFactory

DB_DIR = Path(__file__).resolve().parents[3] / "db"


class Database(Construct):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        vpc: ec2.IVpc,
        key: kms.IKey,
        functions: FunctionFactory,
        removal: RemovalPolicy,
        database_name: str = "claims",
    ) -> None:
        super().__init__(scope, construct_id)
        self.database_name = database_name
        security_group = ec2.SecurityGroup(
            self,
            "DbSg",
            vpc=vpc,
            description="Aurora - no ingress; access is via the RDS Data API",
            allow_all_outbound=False,
        )
        self.cluster = rds.DatabaseCluster(
            self,
            "Cluster",
            engine=rds.DatabaseClusterEngine.aurora_postgres(version=rds.AuroraPostgresEngineVersion.VER_17_9),
            writer=rds.ClusterInstance.serverless_v2(
                "writer", publicly_accessible=False, auto_minor_version_upgrade=True
            ),
            serverless_v2_min_capacity=0.5,
            serverless_v2_max_capacity=4,
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_ISOLATED),
            security_groups=[security_group],
            default_database_name=database_name,
            credentials=rds.Credentials.from_generated_secret("claims_admin", encryption_key=key),
            storage_encrypted=True,
            storage_encryption_key=key,
            enable_data_api=True,
            monitoring_interval=Duration.seconds(60),
            iam_authentication=True,
            backup=rds.BackupProps(retention=Duration.days(7)),
            cloudwatch_logs_exports=["postgresql"],
            cloudwatch_logs_retention=logs.RetentionDays.ONE_MONTH,
            deletion_protection=removal == RemovalPolicy.RETAIN,
            removal_policy=removal,
        )
        self.secret = self.cluster.secret

        schema = s3_assets.Asset(self, "SchemaSql", path=str(DB_DIR / "schema.sql"))
        seed = s3_assets.Asset(self, "SeedSql", path=str(DB_DIR / "seed.sql"))
        version = hashlib.sha256((DB_DIR / "schema.sql").read_bytes() + (DB_DIR / "seed.sql").read_bytes()).hexdigest()

        schema_fn = functions.create(
            self,
            "SchemaFn",
            handler="custom_resources.db_schema.handler",
            description="Applies the claims schema and seed data via the Data API",
            environment=self.data_api_env(),
            timeout=Duration.minutes(10),
        )
        self.grant_data_api(schema_fn)
        schema.grant_read(schema_fn)
        seed.grant_read(schema_fn)
        provider = cr.Provider(self, "SchemaProvider", on_event_handler=schema_fn)
        resource = CustomResource(
            self,
            "Schema",
            service_token=provider.service_token,
            properties={
                "Bucket": schema.s3_bucket_name,
                "SchemaKey": schema.s3_object_key,
                "SeedKey": seed.s3_object_key,
                "Version": version,
            },
        )
        resource.node.add_dependency(self.cluster)

    def data_api_env(self) -> dict[str, str]:
        return {
            "DB_CLUSTER_ARN": self.cluster.cluster_arn,
            "DB_SECRET_ARN": self.secret.secret_arn,
            "DB_NAME": self.database_name,
        }

    def grant_data_api(self, fn) -> None:
        self.cluster.grant_data_api_access(fn)
