import json
from aws_cdk import (
    Duration,
    aws_lambda as _lambda,
    aws_iam as iam,
    aws_opensearchserverless as aoss,
    custom_resources,
)
from constructs import Construct

class VectorStore(Construct):
    def __init__(self, scope: Construct, construct_id: str,
                 kb_service_role_arn:str,
                 vector_store_collection_name:str,
                 vector_store_collection_description:str,
            **kwargs) -> None:

        super().__init__(scope, construct_id, **kwargs)
   
        create_vector_index_lambda_function = self.create_vector_index_lambda_function()
        
        aoss_data_access_policy, aoss_network_access_policy, aoss_encryption_policy = self.create_aoss_policies(
            create_vector_index_lambda_function=create_vector_index_lambda_function,
            vector_store_collection_name=vector_store_collection_name,
            kb_service_role_arn=kb_service_role_arn
        )

        #Create the AOSS Collection
        aoss_collection = aoss.CfnCollection(self,
            "aoss_collection",
            name=vector_store_collection_name,
            type="VECTORSEARCH",
            description=f"{vector_store_collection_description}"
        )
        

        #Add resource dependencies
        aoss_collection.add_dependency (aoss_data_access_policy)
        aoss_collection.add_dependency (aoss_network_access_policy)
        aoss_collection.add_dependency (aoss_encryption_policy)
        
        self.aoss_collection_arn = aoss_collection.attr_arn
        self.aoss_collection_endpoint = aoss_collection.attr_collection_endpoint


    def create_aoss_policies(self,
            create_vector_index_lambda_function:_lambda.Function,
            vector_store_collection_name:str,
            kb_service_role_arn:str
    ):
                #Create the neccessary network policy, encryption policy and data access policy for the OpenSearch serverless collection
        network_policy  = json.dumps([{
            "Description":f"Public access for {vector_store_collection_name} collection",
            "Rules":[{
                "ResourceType":"dashboard",
                "Resource":[
                f"collection/{vector_store_collection_name}"
            ]},
            {
                "ResourceType":"collection",
                "Resource":[
                    f"collection/{vector_store_collection_name}"
                ]
            }],
            "AllowFromPublic":True
        }], indent=2)
        encryption_policy  = json.dumps({
            "Rules":[
                {
                    "ResourceType":"collection",
                    "Resource":[
                        f"collection/{vector_store_collection_name}"
                    ]
                }
            ],
            "AWSOwnedKey":True
        }, indent=2)
        data_access_policy  = json.dumps([{
            "Rules": [{
                "Resource": [
                    f"collection/{vector_store_collection_name}"
                ],
                "Permission": [
                    "aoss:CreateCollectionItems",
                    "aoss:DeleteCollectionItems",
                    "aoss:UpdateCollectionItems",
                    "aoss:DescribeCollectionItems"
                ],
                "ResourceType": "collection"
            },
            {
                "Resource": [
                    f"index/{vector_store_collection_name}/*"
                ],
                "Permission": [
                    "aoss:CreateIndex",
                    "aoss:DeleteIndex",
                    "aoss:UpdateIndex",
                    "aoss:DescribeIndex",
                    "aoss:ReadDocument",
                    "aoss:WriteDocument"
                ],
                "ResourceType": "index"
            }],
            "Principal": [
                create_vector_index_lambda_function.role.role_arn,
                kb_service_role_arn
            ]
        }], indent=2)

        #Create the CFN resources for the security and access policies
        aoss_data_access_policy = aoss.CfnAccessPolicy(self,
            "aoss_data_access_policy",
            name=f"{vector_store_collection_name}-ap",
            description=f"Access policy for Collection {vector_store_collection_name}",
            policy= data_access_policy,
            type="data"
        )  
        aoss_network_access_policy = aoss.CfnSecurityPolicy(self,
            "aoss_network_access_policy",
            name=f"{vector_store_collection_name}-np",
            description=f"Security policy for Collection {vector_store_collection_name}",
            policy= network_policy,
            type="network"
        )
        aoss_encryption_policy = aoss.CfnSecurityPolicy (self,
            "aoss_encryption_policy",
            name=f"{vector_store_collection_name}-ep",
            description=f"Encryption policy for Collection {vector_store_collection_name}",
            policy= encryption_policy,
            type="encryption"
        )
        return (aoss_data_access_policy, aoss_network_access_policy, aoss_encryption_policy )

    def create_vector_index_lambda_function(self) -> _lambda.Function:

        #Create the layer for the lambda function
        layer = _lambda.LayerVersion(self, 'vector_store_index_creation_lambda_layer',
            description='Dependencies for the vector store index creation function',
            code= _lambda.Code.from_asset( 'lambda/claims_review/layer/'), # required
            compatible_runtimes=[
                _lambda.Runtime.PYTHON_3_10
            ],
        )

        # Define the Lambda function resource and give the associated Execution role the permission to call the relevant Bedrock service api to start ingestion job
        vector_store_index_creation_function = _lambda.Function(
            self, 'create_vector_index',
            runtime=_lambda.Runtime.PYTHON_3_10,
            code=_lambda.Code.from_asset('lambda/claims_review/create_vector_index'),
            handler='index.on_event',
            timeout=Duration.seconds(300),
            layers=[layer]
        ) 
        vector_store_index_creation_function.add_to_role_policy(
            iam.PolicyStatement(
                actions=["aoss:*"],
                resources=["*"]
            )
        )
        vector_store_index_creation_function.node.add_dependency(layer)

        #Create the Custom Resource Provider backed by Lambda Function
        self.vector_store_index_creation_provider = custom_resources.Provider(
            self, 'vector_store_index_creation_provider',
            on_event_handler=vector_store_index_creation_function,
            provider_function_name="vector-store-index-creation-provider"
        )

        return vector_store_index_creation_function

