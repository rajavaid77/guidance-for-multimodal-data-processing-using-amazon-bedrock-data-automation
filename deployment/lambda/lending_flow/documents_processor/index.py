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
from bda_wrapper import invoke_insight_generation_async, bda_sdk, get_project_arn
import random, string


BDA_RUNTIME_ENDPOINT = os.environ.get('BDA_RUNTIME_ENDPOINT', None)
DATA_PROJECT_NAME = os.environ.get('DATA_PROJECT_NAME', None)
TARGET_BUCKET_NAME = os.environ.get('TARGET_BUCKET_NAME', None)


s3 = boto3.client("s3")

def get_claim_reference_id(key):
    return key.split('/', 1)[0] if '/' in key else ''.join(random.choices(string.ascii_letters + string.digits, k=6))

def lambda_handler(event, context):

    print(f"Received event: {event}")

    # Generate a unique ID using UUID4
    bucket = event['detail']['bucket']['name']
    key = event['detail']['object']['key']
    key = key.replace("documents", "documents-output")
    input_s3_uri = f"s3://{bucket}/{key}"
    output_s3_uri = f"s3://{TARGET_BUCKET_NAME}/{key}"

    project_arn = get_project_arn(DATA_PROJECT_NAME)

    # invoke insight generation
    response = invoke_insight_generation_async(input_s3_uri, output_s3_uri, data_project_arn=project_arn)

    print(response)
    return response
