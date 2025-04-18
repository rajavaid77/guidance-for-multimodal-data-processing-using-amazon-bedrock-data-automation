from time import time
import json
import boto3
import os

s3 = boto3.client("s3")

session = boto3.Session()  
rds_data = session.client(
    service_name='rds-data'
)

CLAIMS_DB_CLUSTER_ARN = os.environ['CLAIMS_DB_CLUSTER_ARN']
CLAIMS_DB_DATABASE_NAME = os.environ['CLAIMS_DB_DATABASE_NAME']
CLAIMS_DB_CREDENTIALS_SECRET_ARN = os.environ['CLAIMS_DB_CREDENTIALS_SECRET_ARN']


CREATE_CLAIM_EVENT_QUERY = """
    INSERT INTO CLAIM_EVENT(claim_reference, claim_event, claim_status, detail) VALUES (:claim_reference, :claim_event, :claim_status, :detail) RETURNING id;
"""
def lambda_handler(event, context):
    # TODO implement
    print(event)
    if event.get('type') == 'claim-event':
        result = create_claim_event(event)
        print(result)
    return {
        'statusCode': 200,
        'body': json.dumps('Hello from Lambda!')
    }

def run_command(sql_statement, parameters=None):
    print(f"SQL statement: {sql_statement}")
    result = rds_data.execute_statement(
        resourceArn=CLAIMS_DB_CLUSTER_ARN,
        secretArn=CLAIMS_DB_CREDENTIALS_SECRET_ARN,
        database=CLAIMS_DB_DATABASE_NAME,
        sql=sql_statement,
        includeResultMetadata=True,
        parameters=parameters
    )
    return result

# Function to create parameter dict
def create_param(name, value):
    print(f"name:{name}, value:{value}")
    if value is None:
        return {'name': name, 'value': {'isNull': True}}
    elif isinstance(value, str):
        return {'name': name, 'value': {'stringValue': value}}
    elif isinstance(value, int):
        return {'name': name, 'value': {'longValue': value}}
    elif isinstance(value, float):
        return {'name': name, 'value': {'doubleValue': value}}
    elif isinstance(value, bool):
        return {'name': name, 'value': {'booleanValue': value}}
    elif isinstance(value, dict):
        return {'name': name, 'value': {'stringValue': json.dumps(value)}}
    else:
        raise ValueError(f"Unsupported type for {name}: {type(value)}")

def create_claim_event(event) :
    claim_reference = event["claim_reference"].split('/')[0]
    parameters = [
        create_param("claim_reference", claim_reference),
        create_param("claim_event", event["claim_event"]),
        create_param("claim_status", event["status"]),
        create_param("detail", event.get('detail',''))

    ]
    print(parameters)
    result = run_command(sql_statement=CREATE_CLAIM_EVENT_QUERY, parameters=parameters)
    return result