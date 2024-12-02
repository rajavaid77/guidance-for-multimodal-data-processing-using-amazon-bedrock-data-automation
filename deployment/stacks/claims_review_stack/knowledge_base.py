from aws_cdk import (
    aws_bedrock as bedrock,
    aws_iam as iam,
    aws_logs as logs,
    Stack,
    aws_s3 as s3,
    RemovalPolicy,
    aws_events as events,
    aws_events_targets as targets,
    aws_lambda as _lambda,
    CfnOutput
)
import random, string
from constructs import Construct
import uuid
import uuid

class KnowledgeBase(Construct):
    def __init__(self, scope: Construct, construct_id: str,
                 kb_service_role_arn,
                 vector_store_collection_arn,
                 knowledgebase_parameters,
                 datasource_sync_lambda_function: _lambda.Function,
                 **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Create an S3 bucket to store the data files needed for RAG Knowledge Base
        self.datasource_bucket = self.create_datasource_bucket(
            knowledgebase_parameters=knowledgebase_parameters,
        )

        self.knowledgebase = self.create_knowledgebase(
            knowledgebase_parameters=knowledgebase_parameters,
            kb_service_role_arn = kb_service_role_arn,
            vector_store_collection_arn=vector_store_collection_arn
        )
        

        self.knowledgebase_datasource = self.create_s3_datasource(
            knowledgebase=self.knowledgebase,
            knowledgebase_parameters=knowledgebase_parameters
        )



        self.setup_knowledge_base_logging(
                        knowledgebase_parameters=knowledgebase_parameters,
                        knowledge_base_id = self.knowledgebase.attr_knowledge_base_id)

        self.create_eventbridge_rule_for_kb_sync(
            knowledgebase_id=self.knowledgebase.attr_knowledge_base_id,
            knowledgebase_arn=self.knowledgebase.attr_knowledge_base_arn,
            knowledgebase_datasource_id=self.knowledgebase_datasource.attr_data_source_id,
            datasource_bucket=self.datasource_bucket,
            datasource_sync_lambda_function=datasource_sync_lambda_function
        )

        self.output_kb_info(
            knowledge_base_name=knowledgebase_parameters["knowledge_base_name"],
            knowledgebase_id=self.knowledgebase.attr_knowledge_base_id,
            knowledgebase_datasource_id=self.knowledgebase_datasource.attr_data_source_id, # type: ignore
            datasource_bucket_name=self.datasource_bucket.bucket_name
        )
        
        # Grant the Lambda function permission to access the S3 bucket.
        self.datasource_bucket.grant_read(datasource_sync_lambda_function)

        datasource_sync_lambda_function.add_to_role_policy(iam.PolicyStatement(
            actions=["bedrock:StartIngestionJob"],
            resources=[self.knowledgebase.attr_knowledge_base_arn]
        ))


    def create_datasource_bucket(self, 
                        knowledgebase_parameters: dict) -> s3.Bucket:

        knowledge_base_name = knowledgebase_parameters['knowledge_base_name']
        knowledge_base_datasource_parameters = knowledgebase_parameters['datasource_parameters']
        datasource_bucket_name = knowledge_base_datasource_parameters["datasource_bucket_name"]
        random_suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
        bucket = s3.Bucket(self,
            f"{knowledge_base_name}_datasource_bucket",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            event_bridge_enabled=True,
            removal_policy=RemovalPolicy.DESTROY,
        )   
        return bucket
    
    def create_knowledgebase(self, 
                             kb_service_role_arn: iam.Role,
                             vector_store_collection_arn: str,
                             knowledgebase_parameters: dict) -> bedrock.CfnKnowledgeBase:

        knowledge_base_name = knowledgebase_parameters['knowledge_base_name']
        knowledge_base_description = knowledgebase_parameters['knowledge_base_description']
        embedding_model_id = knowledgebase_parameters['embedding_model_id']
        embedding_model_arn = f"arn:aws:bedrock:{Stack.of(self).region}::foundation-model/{embedding_model_id}"

        vector_store_index_name = knowledgebase_parameters['vector_store_index_params']["index_name"]
        metadata_field = knowledgebase_parameters['vector_store_index_params']["metadata_field"]
        text_field = knowledgebase_parameters['vector_store_index_params']['text_field']
        vector_field = knowledgebase_parameters['vector_store_index_params']['vector_field']

        #Create the Bedrock Knowledge Base with the s3 bucket as knowledge base
        return bedrock.CfnKnowledgeBase(self, "knowledgebase",
            name=knowledge_base_name,
            knowledge_base_configuration=bedrock.CfnKnowledgeBase.KnowledgeBaseConfigurationProperty(
                type="VECTOR",
                vector_knowledge_base_configuration=bedrock.CfnKnowledgeBase.VectorKnowledgeBaseConfigurationProperty(
                    embedding_model_arn=f"{embedding_model_arn}"
                )
            ),
            role_arn=kb_service_role_arn,            
            storage_configuration=bedrock.CfnKnowledgeBase.StorageConfigurationProperty(
                type="OPENSEARCH_SERVERLESS",
                # the properties below are optional
                opensearch_serverless_configuration=bedrock.CfnKnowledgeBase.OpenSearchServerlessConfigurationProperty(
                    collection_arn=vector_store_collection_arn,
                    vector_index_name=vector_store_index_name,
                    field_mapping=bedrock.CfnKnowledgeBase.OpenSearchServerlessFieldMappingProperty(
                        metadata_field=metadata_field,
                        text_field=text_field,
                        vector_field=vector_field
                    )
                )
            ),
            description=knowledge_base_description
        )

    def create_s3_datasource(self, 
                knowledgebase: bedrock.CfnKnowledgeBase,
                knowledgebase_parameters: dict) -> bedrock.CfnDataSource:
        # Add a KB datasource with S3 datasource configuration

        knowledge_base_datasource_parameters = knowledgebase_parameters['datasource_parameters']

        datasource = bedrock.CfnDataSource(self, "BedrockKBDataSource",
            name=knowledge_base_datasource_parameters['name'],
            description="Bedrock Knowledgebase DataSource Configuration",
            data_source_configuration=bedrock.CfnDataSource.DataSourceConfigurationProperty(
                s3_configuration=bedrock.CfnDataSource.S3DataSourceConfigurationProperty(
                    bucket_arn=self.datasource_bucket.bucket_arn
                ),
                type="S3"
            ),
            vector_ingestion_configuration=bedrock.CfnDataSource.VectorIngestionConfigurationProperty (
                chunking_configuration=self.get_chunking_configuration_from_parameters(knowledgebase_parameters)
            ),
            knowledge_base_id=knowledgebase.attr_knowledge_base_id
        )
        return datasource

    def setup_knowledge_base_logging(self,
                                     knowledge_base_id: str,
                                     knowledgebase_parameters: dict):
        knowledgebase_logging_parameters = knowledgebase_parameters['logging_parameters']
        kb_cw_log_group_name_prefix = knowledgebase_logging_parameters['kb_cw_log_group_name_prefix']
        bedrock_kb_log_delivery_source = knowledgebase_logging_parameters['kb_log_delivery_source']

        kb_log_group = logs.LogGroup(self,
            "kb_log_group",
            log_group_name=f"/aws/vendedlogs/bedrock/{kb_cw_log_group_name_prefix}-{knowledge_base_id}",
            retention=logs.RetentionDays.ONE_DAY,
            removal_policy=RemovalPolicy.DESTROY 
        )
        kb_log_group.add_to_resource_policy(
            iam.PolicyStatement(
                sid="AWSLogDeliveryWriteBedrockKB20240719",
                effect=iam.Effect.ALLOW,
                principals=[iam.ServicePrincipal('delivery.logs.amazonaws.com')],
                actions=["logs:CreateLogStream", "logs:PutLogEvents"],
                resources=[kb_log_group.log_group_arn],
                conditions={
                    "StringEquals": {
                        "aws:SourceAccount": Stack.of(self).account
                    },
                    "ArnLike": {
                        "aws:SourceArn": f"arn:aws:logs:{Stack.of(self).region}:{Stack.of(self).account}:delivery-source:{bedrock_kb_log_delivery_source}"
                    }
                }
            )
        )
        kb_logs_delivery_destination = logs.CfnDeliveryDestination(self, "kb_logs_delivery_destination",
            name=f"kb-logs-delivery-destination-{knowledge_base_id}",
            destination_resource_arn=kb_log_group.log_group_arn
        )
        kb_logs_delivery_source = logs.CfnDeliverySource(self, "kb_logs_delivery_source",
            name=bedrock_kb_log_delivery_source,
            log_type="APPLICATION_LOGS",
            resource_arn=self.knowledgebase.attr_knowledge_base_arn
        )
        
        # kb_logs_delivery = logs.CfnDelivery(self, "kb_logs_delivery",
        #    delivery_destination_arn=kb_logs_delivery_destination.attr_arn,
        #    delivery_source_name=kb_logs_delivery_source.name,
        #)
        #kb_logs_delivery.add_dependency(kb_logs_delivery_destination)
        #kb_logs_delivery.add_dependency(kb_logs_delivery_source)

    def get_chunking_configuration_from_parameters(self,
                                                   knowledgebase_parameters: dict):
        
        knowledgebase_chunking_parameters = knowledgebase_parameters['datasource_parameters']['chunking_configuration']
        return bedrock.CfnDataSource.ChunkingConfigurationProperty(
            chunking_strategy="FIXED_SIZE",
            fixed_size_chunking_configuration=bedrock.CfnDataSource.FixedSizeChunkingConfigurationProperty(
                max_tokens=1024,
                overlap_percentage=30
            )
        )
    
    def create_eventbridge_rule_for_kb_sync(self,
                                    knowledgebase_id: str,
                                    knowledgebase_arn: str,
                                    knowledgebase_datasource_id: str,
                                    datasource_bucket: s3.Bucket,
                                    datasource_sync_lambda_function: _lambda.Function):
    # Create an EventBridge rule.
        datasource_sync_rule = events.Rule(self, "on_s3_object_create_update_rule",
            event_pattern=events.EventPattern(
                source=["aws.s3"],
                detail_type=["Object Created", "Object Updated"],
                detail={
                    "bucket": {
                        "name": [datasource_bucket.bucket_name]
                    }
                }
            )
        )

        # Define the input transformer
        input_transformer = events.RuleTargetInput.from_object({
            "bucket": events.EventField.from_path("$.detail.bucket.name"),
            "key": events.EventField.from_path("$.detail.object.key"),
            "eventTime": events.EventField.from_path("$.time"),
            "eventName": events.EventField.from_path("$.detail-type"),
            "knowledgebase_id": knowledgebase_id,
            "knowledgebase_datasource_id": knowledgebase_datasource_id
        })

        # Add a target to the rule.
        datasource_sync_rule.add_target(
            targets.LambdaFunction(
                handler=datasource_sync_lambda_function,
                event=input_transformer
            )
        )

    def output_kb_info(self, 
                       knowledge_base_name:str,
                       knowledgebase_id: str, 
                       knowledgebase_datasource_id: str, 
                       datasource_bucket_name):
        
        CfnOutput(self, f"{knowledge_base_name}_id",
                  value=knowledgebase_id,
                  description=f"Knowledge Base Id: {knowledge_base_name}",
                  export_name=f"{knowledge_base_name}-id"
        )
        CfnOutput(self, f"{knowledge_base_name}_datasource_id",
                  value=knowledgebase_datasource_id,
                  description=f"Datasource Id:{knowledge_base_name}",
                  export_name=f"{knowledge_base_name}-datsource-id"
        )
        CfnOutput(self, f"{knowledge_base_name}_datasource_bucket_name",
                export_name=f"{knowledge_base_name}-datasource-bucket",
                value=datasource_bucket_name)
