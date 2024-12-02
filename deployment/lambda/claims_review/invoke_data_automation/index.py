import json
# Lambda function handler that processes incoming S3 claim form submission events and triggers 
# a Bedrock Automation Job
# @param event: The event object containing input data
# @param context: The runtime information provided by AWS Lambda
# @return: A dictionary containing HTTP status code and response body
import json
import uuid
import os
import boto3
from bda_wrapper import invoke_insight_generation_async
import random, string


CLAIMS_REVIEW_BUCKET_NAME = os.environ['CLAIMS_REVIEW_BUCKET_NAME']
DATA_PROJECT_ARN = os.environ.get('DATA_PROJECT_ARN', None)
BLUEPRINT_ARN = os.environ.get('BLUEPRINT_ARN', None)


s3 = boto3.client("s3")

def get_claim_reference_id(key):
    return key.split('/', 1)[0] if '/' in key else ''.join(random.choices(string.ascii_letters + string.digits, k=6))

def lambda_handler(event, context):

    print(f"Received event: {event}")

    # Generate a unique ID using UUID4
    bucket = event['detail']['bucket']['name']
    key = event['detail']['object']['key']
    claim_reference_id = get_claim_reference_id(key)
    print(f"Claim Reference ID: {claim_reference_id}")
    response = invoke_insight_generation_async(
        data_project_arn=DATA_PROJECT_ARN,
        blueprint_arn=BLUEPRINT_ARN,
        claim_reference_id=claim_reference_id,
        input_s3_uri=f"s3://{bucket}/{key}",
        output_s3_uri=f"s3://{CLAIMS_REVIEW_BUCKET_NAME}/{claim_reference_id}"
    )
    print(response)
    return response


