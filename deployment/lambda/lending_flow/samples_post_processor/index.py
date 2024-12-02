import os
import boto3
import json

s3 = boto3.client('s3')
def handler(event, context):
    print(event)
    bucket_name = os.environ['BUCKET_NAME']
    output_prefix = os.environ['OUTPUT_PREFIX']
    
    # Get the source file details
    detail = event['detail']
    source_key = detail['object']['key']
    
    # Process and write output
    output_key = f"{output_prefix}processed-{source_key.split('/')[-1]}"
    
    # Write a simple output file
    content = f"Processed document file: {source_key}"
    s3.put_object(
        Bucket=bucket_name,
        Key=output_key,
        Body=content
    )
    
    return {
        'statusCode': 200,
        'body': json.dumps(f'Processed {source_key} to {output_key}')
    }
