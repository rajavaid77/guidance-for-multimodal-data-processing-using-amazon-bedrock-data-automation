"""Bedrock Knowledge Base over plan policy documents (Evidence of Coverage), stored in Amazon S3 Vectors."""

from __future__ import annotations

import hashlib
from pathlib import Path

from aws_cdk import Stack
from aws_cdk import aws_bedrock as bedrock
from aws_cdk import aws_iam as iam
from aws_cdk import aws_kms as kms
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_s3_deployment as s3deploy
from aws_cdk import aws_s3vectors as s3vectors
from aws_cdk import custom_resources as cr
from constructs import Construct

EOC_DIR = Path(__file__).resolve().parents[4] / "assets" / "data" / "claims_review" / "eoc"
POLICY_DIR = Path(__file__).resolve().parents[3] / "knowledge" / "policies"


def _content_hash(*dirs: Path) -> str:
    digest = hashlib.sha256()
    for d in dirs:
        for f in sorted(d.rglob("*")):
            if f.is_file():
                digest.update(f.relative_to(d).as_posix().encode() + f.read_bytes())
    return digest.hexdigest()[:40]  # StartIngestionJob clientToken needs >= 33 chars


class KnowledgeBase(Construct):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        prefix: str,
        policy_bucket: s3.IBucket,
        key: kms.IKey,
        embedding_model_id: str,
        dimensions: int,
    ) -> None:
        super().__init__(scope, construct_id)
        stack = Stack.of(self)
        embedding_arn = f"arn:{stack.partition}:bedrock:{stack.region}::foundation-model/{embedding_model_id}"

        # Vectors derive from non-PHI plan policy documents; SSE-S3 avoids an S3 Vectors service key grant.
        self.vector_bucket = s3vectors.CfnVectorBucket(
            self,
            "VectorBucket",
            vector_bucket_name=f"{prefix}-policies-{stack.account}",
            encryption_configuration=s3vectors.CfnVectorBucket.EncryptionConfigurationProperty(sse_type="AES256"),
        )
        self.index = s3vectors.CfnIndex(
            self,
            "Index",
            vector_bucket_arn=self.vector_bucket.attr_vector_bucket_arn,
            index_name="policies",
            data_type="float32",
            dimension=dimensions,
            distance_metric="cosine",
            metadata_configuration=s3vectors.CfnIndex.MetadataConfigurationProperty(
                non_filterable_metadata_keys=["AMAZON_BEDROCK_TEXT", "AMAZON_BEDROCK_METADATA"]
            ),
        )

        role = iam.Role(
            self,
            "KbRole",
            assumed_by=iam.ServicePrincipal(
                "bedrock.amazonaws.com",
                conditions={
                    "StringEquals": {"aws:SourceAccount": stack.account},
                    "ArnLike": {
                        "aws:SourceArn": f"arn:{stack.partition}:bedrock:{stack.region}:{stack.account}:knowledge-base/*"
                    },
                },
            ),
        )
        role.add_to_policy(iam.PolicyStatement(actions=["bedrock:InvokeModel"], resources=[embedding_arn]))
        role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "s3vectors:PutVectors",
                    "s3vectors:GetVectors",
                    "s3vectors:DeleteVectors",
                    "s3vectors:QueryVectors",
                    "s3vectors:GetIndex",
                    "s3vectors:ListVectors",
                ],
                resources=[self.index.attr_index_arn],
            )
        )
        policy_bucket.grant_read(role)
        # Decrypt source docs + generate data keys for the data source's transient encryption.
        key.grant_encrypt_decrypt(role)

        K = bedrock.CfnKnowledgeBase
        self.kb = K(
            self,
            "KnowledgeBase",
            name=f"{prefix}-policies",
            description="Health plan Evidence of Coverage and coverage policies used by the Clinical Review agent",
            role_arn=role.role_arn,
            knowledge_base_configuration=K.KnowledgeBaseConfigurationProperty(
                type="VECTOR",
                vector_knowledge_base_configuration=K.VectorKnowledgeBaseConfigurationProperty(
                    embedding_model_arn=embedding_arn,
                    embedding_model_configuration=K.EmbeddingModelConfigurationProperty(
                        bedrock_embedding_model_configuration=K.BedrockEmbeddingModelConfigurationProperty(
                            dimensions=dimensions, embedding_data_type="FLOAT32"
                        )
                    ),
                ),
            ),
            storage_configuration=K.StorageConfigurationProperty(
                type="S3_VECTORS",
                s3_vectors_configuration=K.S3VectorsConfigurationProperty(index_arn=self.index.attr_index_arn),
            ),
        )
        self.kb.node.add_dependency(role)

        D = bedrock.CfnDataSource
        self.data_source = D(
            self,
            "PolicyDocs",
            knowledge_base_id=self.kb.attr_knowledge_base_id,
            name="evidence-of-coverage",
            data_source_configuration=D.DataSourceConfigurationProperty(
                type="S3",
                s3_configuration=D.S3DataSourceConfigurationProperty(
                    bucket_arn=policy_bucket.bucket_arn  # bucket holds only eoc/ and policies/ (max 1 prefix)
                ),
            ),
            server_side_encryption_configuration=D.ServerSideEncryptionConfigurationProperty(kms_key_arn=key.key_arn),
            vector_ingestion_configuration=D.VectorIngestionConfigurationProperty(
                chunking_configuration=D.ChunkingConfigurationProperty(
                    chunking_strategy="FIXED_SIZE",
                    fixed_size_chunking_configuration=D.FixedSizeChunkingConfigurationProperty(
                        max_tokens=512, overlap_percentage=20
                    ),
                )
            ),
        )

        # Load the sample EoC PDFs and run the first ingestion so the demo works after one deploy.
        deployment = s3deploy.BucketDeployment(
            self,
            "EocDocs",
            sources=[s3deploy.Source.asset(str(EOC_DIR))],
            destination_bucket=policy_bucket,
            destination_key_prefix="eoc/",
            server_side_encryption=s3deploy.ServerSideEncryption.AWS_KMS,
            server_side_encryption_aws_kms_key_id=key.key_id,
            prune=False,
            retain_on_delete=False,
        )
        key.grant_encrypt_decrypt(deployment.handler_role)
        policies = s3deploy.BucketDeployment(
            self,
            "PolicyLibrary",
            sources=[s3deploy.Source.asset(str(POLICY_DIR), exclude=["README.md"])],
            destination_bucket=policy_bucket,
            destination_key_prefix="policies/",
            server_side_encryption=s3deploy.ServerSideEncryption.AWS_KMS,
            server_side_encryption_aws_kms_key_id=key.key_id,
            prune=True,
            retain_on_delete=False,
        )
        key.grant_encrypt_decrypt(policies.handler_role)
        # Re-ingest whenever the documents change (clientToken = content hash keeps it idempotent).
        content = _content_hash(EOC_DIR, POLICY_DIR)
        ingest_call = cr.AwsSdkCall(
            service="bedrock-agent",
            action="StartIngestionJob",
            parameters={
                "knowledgeBaseId": self.kb.attr_knowledge_base_id,
                "dataSourceId": self.data_source.attr_data_source_id,
                "clientToken": content,
            },
            physical_resource_id=cr.PhysicalResourceId.of(f"ingestion-{content}"),
        )
        ingest = cr.AwsCustomResource(
            self,
            "InitialIngestion",
            on_create=ingest_call,
            on_update=ingest_call,
            policy=cr.AwsCustomResourcePolicy.from_statements(
                [
                    iam.PolicyStatement(
                        actions=["bedrock:StartIngestionJob"],
                        resources=[self.kb.attr_knowledge_base_arn],
                    )
                ]
            ),
            install_latest_aws_sdk=False,
        )
        ingest.node.add_dependency(deployment)
        ingest.node.add_dependency(policies)
        ingest.node.add_dependency(self.data_source)

    def grant_retrieve(self, grantee: iam.IGrantable) -> None:
        iam.Grant.add_to_principal(
            grantee=grantee, actions=["bedrock:Retrieve"], resource_arns=[self.kb.attr_knowledge_base_arn]
        )
