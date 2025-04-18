import boto3
import json
import os

# Create a Bedrock client
bda_client = boto3.client("bedrock-data-automation-runtime") 

#Write  a Function to get a file from S3 bucket
def get_file_from_s3(bucket_name, key):
    s3 = boto3.client("s3")
    response = s3.get_object(Bucket=bucket_name, Key=key)
    return response['Body'].read().decode('utf-8')
#return json.loads(response['Body'].read().decode('utf-8'))

def get_json_from_s3_resource(bucket_name, key):
    s3 = boto3.resource("s3")
    obj = s3.Object(bucket_name, key)
    return json.loads(obj.get()['Body'].read().decode('utf-8'))

# Put an Object to S3 bucket reading from local folder
def put_file_to_s3(bucket_name, key, file_path):
    s3 = boto3.client("s3")
    s3.upload_file(file_path, bucket_name, key)
    return True




def invoke_insight_generation_async(
        claim_reference_id, 
        input_s3_uri, 
        output_s3_uri,
        data_project_arn, blueprint_arn):

    if not any((blueprint_arn, data_project_arn)):
        raise ValueError("At least one of data_project_arn or blueprint_arn must be provided")

    jobTags = {
        "Claim Id": {claim_reference_id}
    }
    # Define the input configuration
    inputConfiguration = {
        "s3Uri": input_s3_uri
    }

    # Define the output configuration
    outputConfiguration = {
        "s3Uri": output_s3_uri
    }

    # Define the data insight configuration
    dataAutomationConfiguration = {
        "dataAutomationArn": data_project_arn
    } if data_project_arn is not None else None

    blueprints = [
        {"blueprintArn": blueprint_arn}
    ] if blueprint_arn is not None else None

    notificationConfiguration =  { 
        "eventBridgeConfiguration": {
            "eventBridgeEnabled" : True 
        }
    }

    print(f"dataAutomationConfiguration:{dataAutomationConfiguration}")
    print(f"blueprints:{blueprints}")
    # Invoke the insight generation async command
    response = bda_client.invoke_data_automation_async(
        inputConfiguration=inputConfiguration,
        **(
            {
                'dataAutomationConfiguration': dataAutomationConfiguration
            } if dataAutomationConfiguration is not None else {}
        ),
        **(
            {
                'blueprints': blueprints
            } if blueprints is not None else {}
        ),
        outputConfiguration=outputConfiguration,
        notificationConfiguration=notificationConfiguration
    )
    print(response)