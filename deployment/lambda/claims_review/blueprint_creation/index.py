import os
import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
import requests
import json
from urllib.parse import quote_plus

ENDPOINT = os.environ.get('ENDPOINT', None)
BLUEPRINT_NAME = os.environ.get('BLUEPRINT_NAME', None)
from requests_aws4auth import AWS4Auth

class InvalidRequestTypeError(ValueError):
    pass

class BlueprintNotFoundError(ValueError):
    pass

# Create a Bedrock client
bda_client = boto3.client("bedrock-data-automation-runtime", 
                                **({'endpoint_url': ENDPOINT} if ENDPOINT is not None else {}),
                                verify=False)

session = boto3.Session()
region_name = session.region_name
service_name ="bedrock"
credentials = session.get_credentials().get_frozen_credentials()

def send_request(url, method, payload=None, service=service_name, region=region_name):
    host = url.split("/")[2]
    request = AWSRequest(
            method,
            url,
            data=payload,
            headers={'Host': host, 'Content-Type':'application/json'}
    )    
    SigV4Auth(credentials, service, region).add_auth(request)
    response = requests.request(method, url, headers=dict(request.headers), data=payload, timeout=50)
    response.raise_for_status()
    print(response)
    content = response.content.decode("utf-8")
    print(content)
    data = json.loads(content)
    return data


def load_blueprint_schema():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    schema_path = os.path.join(current_dir, "blueprint_schema.json")
    with open(schema_path, "r") as f:
        return json.dumps(json.load(f))

def create_payload(blueprint_name, schema, blueprint_stage="LIVE"):
    payload = {
        "blueprintName": blueprint_name,
        "schema": schema,
        "type": "DOCUMENT",
        "blueprintStage": blueprint_stage
    }
    return payload

def update_blueprint(event):
    print(event)

def delete_blueprint(event):
    print(event)

def get_blueprint(event):
    #strip trailing / 
    url = f"{bda_client.meta.endpoint_url.rstrip('/')}/blueprints/"
    response = send_request(
        url = url,
        method = "POST"
    )
    blueprint = next((blueprint for blueprint in response["blueprints"] if blueprint["blueprintName"]==BLUEPRINT_NAME), None)    
    if not blueprint:
        raise BlueprintNotFoundError(f"Blueprint {BLUEPRINT_NAME} not found")
    return blueprint
    
def create_blueprint(event):
    url = f"{bda_client.meta.endpoint_url}/blueprints/"
    print(url)
    list_results = send_request(
        url = url,
        method = "PUT", 
        payload=create_payload(
            blueprint_name=BLUEPRINT_NAME,
            schema=load_blueprint_schema(),
            blueprint_stage="LIVE"
        )
    )
    print(list_results)


def on_event(event, context):
    """
    This function is the entry point for the Lambda function.
    It receives an event and a context object, and based on the request type
    in the event, it calls the appropriate function to handle the request.
    """
    print(event)
    request_type = event['RequestType']
    if request_type == 'Create': return on_create(event)
    if request_type == 'Update': return on_update(event)
    if request_type == 'Delete': return on_delete(event)
    raise InvalidRequestTypeError(f"Invalid request type: {request_type}")

def on_create(event):
    """
    This function is called when a new resource is being created.
    It prints the resource properties, calls the create_or_update_index function
    to create or update the index, and returns the response from that function.
    """
    response = {}
    props = event["ResourceProperties"]
    print("create new resource with props %s" % props)
    #response = create_blueprint(event)
    response = get_blueprint(event)
    return {
        "Data": {
            "blueprintArn": response["blueprintArn"]
        }
    }

def on_update(event):
    """
    This function is called when an existing resource is being updated.
    It prints the resource properties, calls the create_or_update_index function
    to create or update the index, and returns the response from that function.
    """
    response = {}
    props = event["ResourceProperties"]
    print("create new resource with props %s" % props)
    #response = update_blueprint(event)
    #print(response)
    return {
        "Data": {
            "response": response
        }
    }

def on_delete(event):
    """
    This function is called when a resource is being deleted.
    It returns the physical resource ID of the resource being deleted.
    """
    physical_id = event["PhysicalResourceId"]
    return {'PhysicalResourceId': physical_id}

def is_complete(event, context):
    """
    This function checks if the resource is in a stable state based on the request type.
    It returns a dictionary indicating whether the resource is complete or not.
    """
    physical_id = event["PhysicalResourceId"]
    request_type = event["RequestType"]

    # check if resource is stable based on request_type
    # is_ready = ...

    return {'IsComplete': True}
