import boto3
import json

class InvalidRequestTypeError(ValueError):
    pass

    
# Create a Bedrock client
bedrock_client = boto3.client("bedrock")
def get_inference_profile(inference_profile_id:str):

    response = bedrock_client.get_inference_profile(
        inferenceProfileIdentifier=inference_profile_id
    )
    return  {
        "inferenceProfileArn": response["inferenceProfileArn"],
        "model_arns": [model["modelArn"] for model in response["models"]]
    }




def on_event(event, context):
    """
    This function is the entry point for the Lambda function.
    It receives an event and a context object, and based on the request type
    in the event, it calls the appropriate function to handle the request.
    """
    resourceProperties = event["ResourceProperties"]
    request_type = event['RequestType']
    if "inferenceProfileId" not in resourceProperties:
        raise ValueError("inferenceProfileId not provided in the resource properties")
    inferenceProfileId = resourceProperties["inferenceProfileId"]
    response = None
    if request_type in ['Create','Update']:
        inference_profile = get_inference_profile(inferenceProfileId)
        response = {
            "PhysicalResourceId": inferenceProfileId,
            "Data": inference_profile
        }
    if request_type == 'Delete':
        physical_id = event["PhysicalResourceId"]
        response = {'PhysicalResourceId': physical_id}
    print(response)
    return response

