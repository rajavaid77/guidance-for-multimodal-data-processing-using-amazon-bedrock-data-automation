from aws_cdk import (
    CfnOutput,
    Stack,
    aws_s3 as s3,
    aws_lambda as lambda_,
    aws_events as events,
    aws_s3_deployment as s3_deployment,
    aws_events_targets as targets,
    RemovalPolicy
)
from constructs import Construct

class LendingFlowStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Create S3 bucket
        bucket = s3.Bucket(
            self, "bucket",
            auto_delete_objects=True,  # For demo purposes
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.DESTROY,  # For demo purposes
        )

        # Enable EventBridge notifications for the S3 bucket
        bucket.enable_event_bridge_notification()

        # Pre-create folders by uploading empty ".placeholder" files
        for prefix in ['samples/', 'samples-output/', 'documents/', 'documents-output/']:
            s3_deployment.BucketDeployment(
                self, f"Deploy{prefix.replace('/', '')}",
                sources=[s3_deployment.Source.data(f"{prefix.replace('/', '')}.placeholder", "")],  # Use empty string
                destination_bucket=bucket,
                destination_key_prefix=prefix
            )

        # Lambda function configuration
        def create_lambda_function(id: str, folder: str, output_prefix: str = None):
            environment = {"BUCKET_NAME": bucket.bucket_name}
            if output_prefix:
                environment["OUTPUT_PREFIX"] = output_prefix

            return lambda_.Function(
                self, id,
                runtime=lambda_.Runtime.PYTHON_3_9,
                handler="index.handler",
                code=lambda_.Code.from_asset(f"lambda/lending_flow/{folder}"),
                environment=environment,
            )

        # Create Lambda functions
        samples_processor = create_lambda_function("SamplesProcessor", "samples_processor", "samples-output/")
        samples_post_processor = create_lambda_function("SamplesPostProcessor", "samples_post_processor")
        documents_processor = create_lambda_function("DocumentsProcessor", "documents_processor", "documents-output/")
        documents_post_processor = create_lambda_function("DocumentsPostProcessor", "documents_post_processor")

        # Grant permissions
        bucket.grant_read_write(samples_processor)
        bucket.grant_read(samples_post_processor)
        bucket.grant_read_write(documents_processor)
        bucket.grant_read(documents_post_processor)

        # EventBridge rules
        # EventBridge rules for specific prefixes
        def create_event_rule(id: str, prefix: str, target: lambda_.IFunction):
            rule = events.Rule(
                self, id,
                event_pattern=events.EventPattern(
                    source=["aws.s3"],  # S3 events
                    detail_type=["Object Created"],  # Covers all object creation events
                    detail={
                        "bucket": {"name": [bucket.bucket_name]},  # Filter for the specific bucket
                        "object": {"key": [{"prefix": prefix}]}  # Filter for the specific prefix
                    },
                )
            )
            rule.add_target(targets.LambdaFunction(target))

        # Input and output rules
        create_event_rule("SamplesRule", "samples/", samples_processor)
        create_event_rule("SamplesPostProcessorRule", "samples-output/", samples_post_processor)
        create_event_rule("DocumentsRule", "documents/", documents_processor)
        create_event_rule("DocumentsPostProcessorRule", "documents-output/", documents_post_processor)
        # Define an output for the bucket name
        CfnOutput(self, "lending-flow-bucket", value=bucket.bucket_name)