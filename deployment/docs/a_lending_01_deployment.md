# S3 Event Processing with AWS CDK

This project implements an event-driven architecture using S3, EventBridge, and Lambda functions using AWS CDK.

## Architecture Overview

The project sets up:
- An S3 bucket with specific prefixes (samples/, documents/, samples-output/, documents-output/)
- EventBridge rules to monitor S3 events
- Three Lambda functions for processing files:
  - Samples Processor: Processes files in samples/
  - Documents Processor: Processes files in documents/
  - Post Processor: Processes files in output directories

## Prerequisites

- Python 3.9 or higher
- AWS CLI configured with appropriate credentials
- Node.js and npm (for AWS CDK CLI)
- AWS CDK CLI installed (`npm install -g aws-cdk`)

## Project Structure

```
deployment/
├── app.py                                   # Main CDK app entry point
├── cdk.json                                 # CDK configuration
├── cdk.context.json                         # CDK context
├── requirements.txt                         # Python dependencies
├── docs
│   ├── a_lending_01_deployment.md
│   ├── a_lending_02_setup_blueprints.md
│   ├── a_lending_03_run_flow.md
├── stacks/
│   └── lending_flow_stack.py                # Main stack
└── lambda/                                  # Lambda Function Code
     └── lending_flow/
        ├── samples_processor/
        │   └── index.py
        ├── documents_processor/
        │   └── index.py
        │── documents_post_processor/
        │   └── index.py
        ├── samples_post_processor/
            └── index.py

```

## Setup Instructions

1. Create and activate a virtual environment:
```bash
cd guidance-for-document-processing-using-amazon-bedrock-keystone/deployment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

2. Install required dependencies:
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

3. Bootstrap AWS CDK (first-time only):
```bash
cdk bootstrap
```
For more details, read the [AWS CDK Bootstrap Instructions](https://docs.aws.amazon.com/cdk/v2/guide/bootstrapping-env.html)

4. Deploy the lending flow stack:

```bash
cdk deploy lending-flow --require-approval never 
```

General cdk commands
```bash
cdk synth   # Synthesize CloudFormation template
cdk diff    # Review changes
cdk deploy  # Deploy stack
```

## Lambda Functions
The stack deploys three lambda functions as decribe below

### Samples Processor
- Triggered by files uploaded to `samples/` prefix
- Processes sample files
- Outputs results to `samples-output/` prefix

### Documents Processor
- Triggered by files uploaded to `documents/` prefix
- Processes document files
- Outputs results to `documents-output/` prefix

### Post Processor
- Triggered by files created in either output prefix
- Performs final processing on output files

## Deployment Validation

<Provide steps to validate a successful deployment, such as terminal output, verifying that the resource is created, status of the CloudFormation template, etc.>

**Examples:**

* Open CloudFormation console and verify the status of the template with the name starting with xxxxxx.
* If deployment is successful, you should see an active database instance with the name starting with <xxxxx> in        the RDS console.
*  Run the following CLI command to validate the deployment: ```aws cloudformation describe xxxxxxxxxxxxx```

## Running the Guidance 

<Provide instructions to run the Guidance with the sample data or input provided, and interpret the output received.> 

This section should include:

* Guidance inputs
* Commands to run
* Expected output (provide screenshot if possible)
* Output description

## Useful Commands

```bash
# CDK Commands
cdk ls          # List all stacks
cdk synth       # Synthesize CloudFormation template
cdk deploy      # Deploy stack
cdk diff        # Compare deployed stack with current state
cdk destroy     # Remove stack



## Clean Up

To remove all resources:
```bash
cdk destroy
```

## Environment Variables

Each Lambda function uses the following environment variables:

```python
# Samples/Documents Processor
BUCKET_NAME     # S3 bucket name
OUTPUT_PREFIX   # Output directory prefix

# Post Processor
BUCKET_NAME     # S3 bucket name
```

## Security

- Lambda functions use least-privilege permissions
- S3 bucket is configured with appropriate access policies
- EventBridge rules are scoped to specific prefixes

## Troubleshooting

1. Deployment Issues:
   - Verify AWS credentials are configured
   - Ensure CDK is bootstrapped in your account/region
   - Check CloudFormation console for detailed error messages

2. Runtime Issues:
   - Check CloudWatch Logs for Lambda function errors
   - Verify S3 event notifications are enabled
   - Ensure IAM permissions are correct

3. Common Errors:
   - "Resource not found": Ensure resources exist and permissions are correct
   - "Access denied": Check IAM roles and policies
   - "Invalid handler": Verify Lambda function handler names

## Development

To modify the stack:
1. Update `s3_event_processing_stack.py`
2. Update Lambda function code in respective directories
3. Run `cdk diff` to review changes
4. Deploy with `cdk deploy`

## Contributing

1. Create a new branch for features
2. Update documentation as needed
3. Test changes thoroughly
4. Submit pull request

## Useful Links

- [AWS CDK Python Reference](https://docs.aws.amazon.com/cdk/api/v2/python/index.html)
- [AWS Lambda Developer Guide](https://docs.aws.amazon.com/lambda/latest/dg/welcome.html)
- [Amazon EventBridge User Guide](https://docs.aws.amazon.com/eventbridge/latest/userguide/eb-what-is.html)
- [Amazon S3 Developer Guide](https://docs.aws.amazon.com/AmazonS3/latest/dev/Welcome.html)
