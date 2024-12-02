import json

def handler(event, context):
    # Get the processed file details
    detail = event['detail']
    source_key = detail['object']['key']
    
    print(f"Post Processor! Processed file: {source_key}")
    
    return {
        'statusCode': 200,
        'body': json.dumps(f' Documents Post Processor! Noticed file: {source_key}')
    }