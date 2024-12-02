import boto3
import json
import os

ENDPOINT = os.environ.get('ENDPOINT', None)

# Create a Bedrock client
bda_client = boto3.client("bedrock-data-automation-runtime", 
                                **({'endpoint_url': ENDPOINT} if ENDPOINT is not None else {}),
                                verify=False)

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