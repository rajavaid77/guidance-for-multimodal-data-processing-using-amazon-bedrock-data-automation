from aws_cdk import (
    Stack,
    aws_ec2 as ec2,
    aws_rds as rds,
    aws_secretsmanager as secretsmanager,
    Duration,
    aws_lambda as _lambda,
    aws_s3_assets as s3_assets,
    aws_iam as iam,
    custom_resources,
    CustomResource
)
import os
from datetime import datetime,timezone
from constructs import Construct


class AuroraPostgresCluster(Construct):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:

        super().__init__(scope, construct_id, **kwargs)

        # Create a VPC for the Aurora Serverless cluster
        vpc = ec2.Vpc(self, "AuroraVpc",
                        max_azs=2  # Limit to 2 availability zones for cost-saving
                      )

        # Create a secret to store database credentials
        db_credentials_secret = secretsmanager.Secret(self, "DBCredentialsSecret",
                                                      secret_name="AuroraPostgresCredentials",
                                                      generate_secret_string=secretsmanager.SecretStringGenerator(
                                                          exclude_punctuation=True,
                                                          include_space=False,
                                                          generate_string_key="password",
                                                          secret_string_template='{"username": "postgres"}'
                                                      )
                                                      )

        self.default_database_name = "claimdatabase"

        # Define the Aurora Serverless cluster
        self.aurora_cluster = rds.ServerlessCluster(self, "AuroraPostgresCluster",
                                               engine=rds.DatabaseClusterEngine.aurora_postgres(
                                                   version=rds.AuroraPostgresEngineVersion.VER_13_6  # Specify your desired version
                                               ),
                                               vpc=vpc,
                                               credentials=rds.Credentials.from_secret(db_credentials_secret),
                                               default_database_name=self.default_database_name,  # Optional: specify DB name
                                               scaling=rds.ServerlessScalingOptions(
                                                   auto_pause=Duration.minutes(10),  # Auto-pause after 10 minutes of inactivity
                                                   min_capacity=rds.AuroraCapacityUnit.ACU_2,  # Minimum capacity (2 ACUs)
                                                   max_capacity=rds.AuroraCapacityUnit.ACU_8   # Maximum capacity (8 ACUs)
                                               ),
                                               enable_data_api=True  # Enable Data API for serverless Aurora
                                               )

        # Output the cluster endpoint and secret ARN
        self.output_cluster_info(self.aurora_cluster, db_credentials_secret)

        self.db_credentials_secret = db_credentials_secret.secret_arn

        create_schema_file, delete_schema_file = self.create_schema_file_assets()

        manage_schema_lambda_function = self.create_manage_schema_lambda_function(
            cluster_arn=self.aurora_cluster.cluster_arn,
            db_credentials_secret_arn=self.db_credentials_secret,
            create_schema_file_uri=create_schema_file.s3_object_url,
            delete_schema_file_uri=delete_schema_file.s3_object_url            
        )
        self.create_create_schema_custom_resource(manage_schema_lambda_function)


    def output_cluster_info(self, cluster: rds.ServerlessCluster, secret: secretsmanager.Secret) -> None:

        from aws_cdk import CfnOutput

        CfnOutput(self, "ClusterEndpoint",
                  value=cluster.cluster_endpoint.hostname,
                  description="The endpoint of the Aurora PostgreSQL Serverless cluster",
                  export_name="AuroraClusterEndpoint"
                  )
        
        CfnOutput(self, "ClusterArn",
                  value=cluster.cluster_arn,
                  description="The ARN of the Aurora PostgreSQL Serverless cluster",
                  export_name="AuroraClusterArn"
                  )

        CfnOutput(self, "SecretArn",
                  value=secret.secret_arn,
                  description="The ARN of the Secrets Manager secret storing DB credentials",
                  export_name="AuroraSecretArn"
                  )
        
    def create_create_schema_custom_resource(self, 
                                             manage_schema_lambda_function: _lambda.Function):
 
        # Create Custom Resource provider
        provider = custom_resources.Provider(
            self, 
            "manage_schema_provider",
            on_event_handler=manage_schema_lambda_function)

        # Create Custom Resource to execute schema
        manage_schema_custom_resource = CustomResource(
            self,
            "manage_aurora_schema",
            service_token=provider.service_token,
            properties={
                "timestamp": str(datetime.now(timezone.utc))  # Force update on each deployment
            }
        )
        manage_schema_custom_resource.node.add_dependency(self.aurora_cluster)
    
    def create_schema_file_assets(self):
        current_dir = os.path.dirname(os.path.abspath(__file__))

        # Upload the SQL schema file to S3 as an asset
        create_schema_file = s3_assets.Asset(
            self,
            "CreateSQLSchemaAsset",
            path=os.path.join(current_dir, "schemas/create_database_schema.sql"),
        )
        # Upload the SQL schema file to S3 as an asset
        delete_schema_file = s3_assets.Asset(
            self,
            "DeleteSQLSchemaAsset",
            path=os.path.join(current_dir, "schemas/delete_database_schema.sql"),
        )
        return (create_schema_file, delete_schema_file)
    
    def create_manage_schema_lambda_function(self,
            cluster_arn:str,
            db_credentials_secret_arn:str,
            create_schema_file_uri:str,
            delete_schema_file_uri:str
        ):
               # Define the Lambda function that will execute the schema
        manage_schema_lambda_function = _lambda.Function(
            self,
            "SchemaExecutorLambda",
            runtime=_lambda.Runtime.PYTHON_3_10,
            handler="index.handler",
            code=_lambda.Code.from_asset("lambda/claims_review/manage_schema"),
            environment={
                "CLUSTER_ARN": cluster_arn,
                "SECRET_ARN": db_credentials_secret_arn,
                "DATABASE_NAME": "claimdatabase",
                "CREATE_SCHEMA_FILE": create_schema_file_uri,  # Path to the uploaded SQL file in S3
                "DELETE_SCHEMA_FILE": delete_schema_file_uri,  # Path to the uploaded SQL file in S3
            },
        )

        # Grant permissions for Lambda to access RDS Data API and Secrets Manager
        manage_schema_lambda_function.add_to_role_policy(
            iam.PolicyStatement(
                actions=["rds-data:*", "secretsmanager:GetSecretValue", "s3:GetObject"],
                resources=["*"],
            )
        )
        manage_schema_lambda_function.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "rds-data:ExecuteStatement",
                    "rds-data:BatchExecuteStatement",
                    "secretsmanager:GetSecretValue",
                    "s3:GetObject",
                ],
                resources=[
                    f"{cluster_arn}",  # The ARN for your Aurora Serverless cluster
                    f"{db_credentials_secret_arn}",  # The ARN for your Secrets Manager secret storing DB credentials
                ],
            )
        )
        return manage_schema_lambda_function