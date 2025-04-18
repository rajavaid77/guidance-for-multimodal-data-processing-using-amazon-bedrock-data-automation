import json
import os
import boto3
from botocore.config import Config
import requests
import base64
from urllib.parse import urlparse

STACK_NAME = "claims-review"


def get_current_region():
    session = boto3.Session()
    return session.region_name

#given a stack name get an output using a provided export name
def get_stack_output(stack_name, export_name):

    # Configure retry strategy
    try:
        # Create client with retry configuration
        client = boto3.client('cloudformation',region_name=get_current_region())
        response = client.describe_stacks(StackName=stack_name)
        stack = response['Stacks'][0]
    except client.exceptions.ClientError as e:
        # Handle stack not found or other AWS exceptions
        print(f"Error describing stack: {e}")
        return None
    outputs = stack['Outputs']
    output = next(output for output in outputs if output.get('ExportName','') == export_name)
    return output['OutputValue']

def get_claims_submission_bucket_name():
    claims_submission_bucket_name = get_stack_output(STACK_NAME, "claims-submission-bucket")
    return claims_submission_bucket_name

def get_eoc_knowledge_base_id():
    eoc_knowledge_base_id = get_stack_output(STACK_NAME, "claims-eoc-kb-id")
    return eoc_knowledge_base_id

def get_claims_review_bucket_name():
    claims_review_bucket_name = get_stack_output(STACK_NAME, "claims-review-bucket")
    return claims_review_bucket_name

def get_claims_eoc_bucket_name():
    claims_eoc_bucket_name = get_stack_output(STACK_NAME, "claims-eoc-knowledge-base-datasource-bucket-name")
    return claims_eoc_bucket_name

def get_aurora_secret_arn():
    claim_database_secret_arn = get_stack_output(STACK_NAME, "ClaimsDatabaseSecretArn")
    return claim_database_secret_arn

def get_aurora_cluster_arn():
    claims_database_cluster_arn = get_stack_output(STACK_NAME, "ClaimsDatabaseClusterArn")
    return claims_database_cluster_arn

def get_aurora_database_name():
    claims_database_name = get_stack_output(STACK_NAME, "ClaimsDatabaseName")
    return claims_database_name


def is_url(string):
    try:
        result = urlparse(string)
        return all([result.scheme, result.netloc])
    except:
        return False
    
def show_pdf(file_path):
    # Display PDF from URL
    if not file_path:
        return
    if is_url(file_path):
        try:
            response = requests.get(file_path)
            print(response)
            base64_pdf = base64.b64encode(response.content).decode('utf-8')
        except Exception as e:
            st.error(f"Error loading PDF from URL: {e}")
            return
    # Display PDF from local file
    else:
        try:
            with open(file_path, "rb") as f:
                base64_pdf = base64.b64encode(f.read()).decode('utf-8')
        except Exception as e:
            raise e

    return base64_pdf
