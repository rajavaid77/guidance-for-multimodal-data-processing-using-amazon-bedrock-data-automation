import json
import os
import boto3

# Specify the Knowledge Base ID
bedrock_agent_client = boto3.client('bedrock-agent')

def lambda_handler(event, context):


    print(event)
    response = bedrock_agent_client.start_ingestion_job(
        dataSourceId=event["knowledgebase_datasource_id"],
        knowledgeBaseId=event["knowledgebase_id"],
        description=f"Knowledge Base Sync triggered by S3: Bucket={event['bucket']}, key={event['key']}"
    )
    message = f"Ingestion job with ID: {response['ingestionJob']['ingestionJobId']} started at {response['ingestionJob']['startedAt'] } with current status:{response['ingestionJob']['status']}"
    # Print the sync job ID
    print(message)
    return {
        'statusCode': 200,
        'body': json.dumps({
            'result': message
        })
    }   