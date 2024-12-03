from aws_cdk import (
    CfnOutput,
    Stack,
    aws_iam as iam,
    aws_s3 as s3,
    aws_lambda as _lambda,
    Duration,
    aws_events as events,
    aws_s3_deployment as s3_deployment,
    aws_events_targets as targets,
    RemovalPolicy
)
from constructs import Construct
from typing import Optional


class LendingFlowStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        data_project_name = self.node.try_get_context("data_project_name")
        bda_runtime_endpoint = self.node.try_get_context("bda_runtime_endpoint")

        # Create S3 bucket
        bucket = s3.Bucket(
            self,
            "bucket",
            auto_delete_objects=True,  # For demo purposes
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.DESTROY,  # For demo purposes
        )

        # Enable EventBridge notifications for the S3 bucket
        bucket.enable_event_bridge_notification()

        # Pre-create folders by uploading empty ".placeholder" files
        prefixes = ['samples/', 'samples-output/', 'documents/', 'documents-output/']
        for prefix in prefixes:
            s3_deployment.BucketDeployment(
                self,
                f"Deploy{prefix.replace('/', '')}",
                sources=[s3_deployment.Source.data(f"{prefix.replace('/', '')}.placeholder", "")],
                destination_bucket=bucket,
                destination_key_prefix=prefix
            )

        # Lambda function to trigger bedrock data insight
        invoke_data_automation_lambda_function = self.create_invoke_data_automation_function(
            bucket.bucket_name,
            **({'bda_runtime_endpoint': bda_runtime_endpoint} if bda_runtime_endpoint is not None else {}),
            **({'data_project_name': data_project_name} if data_project_name is not None else {})
        )

        # Grant permissions
        bucket.grant_read_write(invoke_data_automation_lambda_function)

        # EventBridge rules for specific prefixes
        def create_event_rule(id: str, prefix: str, target: _lambda.IFunction):
            rule = events.Rule(
                self,
                id,
                event_pattern=events.EventPattern(
                    source=["aws.s3"],
                    detail_type=["Object Created"],
                    detail={
                        "bucket": {"name": [bucket.bucket_name]},
                        "object": {"key": [{"prefix": prefix}]}
                    },
                )
            )
            rule.add_target(targets.LambdaFunction(target))

        # Create rule for documents
        create_event_rule("DocumentsRule", "documents/", invoke_data_automation_lambda_function)

        # Define an output for the bucket name
        CfnOutput(self, "lending-flow-bucket", value=bucket.bucket_name)

    def create_invoke_data_automation_function(self,
            target_bucket_name: s3.Bucket,
            data_project_name: Optional[str] = None,
            bda_runtime_endpoint: Optional[str] = None
    ):
        # Create layer
        layer = _lambda.LayerVersion(
            self,
            'invoke_data_automation_lambda_layer',
            description='Dependencies for the document automation lambda function',
            code=_lambda.Code.from_asset('lambda/lending_flow/layer/'),
            compatible_runtimes=[_lambda.Runtime.PYTHON_3_10],
        )

        lending_document_automation_lambda_function = _lambda.Function(
            self,
            'invoke_data_automation',
            runtime=_lambda.Runtime.PYTHON_3_10,
            code=_lambda.Code.from_asset('lambda/lending_flow/documents_processor'),
            handler='index.lambda_handler',
            timeout=Duration.seconds(300),
            layers=[layer],
            environment={
                k: v
                for k, v in {
                    'TARGET_BUCKET_NAME': target_bucket_name,
                    'BDA_RUNTIME_ENDPOINT': bda_runtime_endpoint,
                    'DATA_PROJECT_NAME': data_project_name,
                }.items()
                if v is not None
            }
        )

        lending_document_automation_lambda_function.add_to_role_policy(iam.PolicyStatement(
            actions=["bedrock:InvokeDataAutomationAsync"],
            resources=["*"]
        ))

        return lending_document_automation_lambda_function