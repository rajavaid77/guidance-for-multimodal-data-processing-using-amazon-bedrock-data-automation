# Claims Review Bedrock Agent Stack Documentation

## Overview

The `claims-review` is an AWS CDK stack that sets up an Amazon Bedrock agentic architecture to automate the processing and review of medical insurance claim forms using Amazon Bedrock Data Automation.

## Architecture Overview

The stack sets up the following key AWS resources: 

> [!Important]
>The resource names or name prefixes would change if the parameters in `cdk.json` are modified from their default values before creating the stack

- Claims Submission Bucket - Used to store incoming CMS 1500 claim forms
  - bucket name prefix `claims-review-bdaclaimsreviewbucket`

- EventBridge Rule - To capture the event when a new claims form is submitted and stored in the Claims Submission Bucket
  - Rule name prefix `claims-review-bdaonclaimsubmission`

- Invoke Data Automation Lambda Function - A Lambda function to trigger Bedrock Data Automation job that gathers insights from the claims form.
  - Function Name Prefix `claims-review-bdainvokedataautomation`

- EventBridge Rule - To capture the event when a the BDA insight job is completed. The rules has a target Lambda function that then triggers Bedrock Agent
  - Rule name prefix `claims-review-bdadataautomationcompleted`

- Invoke Claim Verification Lambda Function - A Lambda function to trigger Bedrock Agent to a prompt to start claim verification steps.
  - Function Name Prefix `claims-review-bdainvokeverification`

- Bedrock Agent to review claims
  - Agent Nae `claims-review-agent`

- Bedrock Knowledge Base to store Claims Evidence of Coverage (EoC) documents for the various Insurance plans
  - Knowledge Base Name `claims-eoc-kb`

- OpenSearch Serverless Collection/Index to serve as vector store for the EoC documents embeddings
  - Collection Name `claims-vector-store`
  - Index Name `claims_eoc_index`
  
- Custom resource with Lambda function to create Opensearch vector index 
  - function name prefix `claims-review-vectorstorecreatevectorindex`

- Aurora PostgreSQL Serverless Database
  - cluster name prefix `claims-review-auroraaurorapostgrescluster`
  - database name `claimdatabase`

- Custom resource with Lambda function to create initial claims database schema and sample data
  - function name prefix `claims-review-auroraSchemaExecutor`

- S3 Bucket to store Claims EoC documents
  - bucket name prefix `claims-review-claimseockbclaimseockbdatasource`

- EventBridge rule to match event when Claim EoC documents are added/updated. The rule triggers the lambda function to start ingestion job
  - rule name prefix `claims-review-claimseockbons3objectcreateupdaterule`

- Lambda Function to trigger datasource Sync for Claims EoC Knowledge Base
  - function name prefix `claims-review-datasourcesynclambdafunction`


## Prerequisites

- Python 3.10 or higher
- AWS CLI configured with appropriate credentials
- Node.js and npm (for AWS CDK CLI)
- AWS CDK CLI installed (`npm install -g aws-cdk`)
- [Ensure Amazon Bedrock Model Access](https://docs.aws.amazon.com/bedrock/latest/userguide/model-access-modify.html)
  - Enable access to 
    * Titan Text G1 - Premier (model id: amazon.titan-text-premier-v1:0)
    * Titan Text Embeddings V2 (model id: amazon.titan-embed-text-v2:0)

## Project Structure
<details>
  <summary>Click for Project Structure</summary>

```
guidance-for-intelligent-document-processing-using-amazon-bedrock/
├── assets/
│   ├── data/
│   │   ├── claims_review/
│   │   │   ├── cms_1500/
│   │   │   │   ├── sample1_cms-1500-P.pdf
│   │   │   │   ├── sample2_cms-1500-P.pdf
│   │   │   │   └── sample3_cms-1500-P.pdf
│   │   │   └── eoc/
│   │   │       ├── Evidence_of_Coverage_-_FakeHealth_Plus.pdf
│   │   │       ├── Evidence_of_Coverage_-_FakeHealth_Premium.pdf
│   │   │       └── Evidence_of_Coverage_-_FakeHealth_Standard.pdf
├── claims-cli.bat
├── claims-cli.sh
├── deployment/
│   ├── app.py
│   ├── cdk.json
│   ├── docs/
│   │   ├── b_claims_review_01_deploy.md
│   │   └── b_claims_review_02_run_flow.md
│   ├── lambda/
│   │   ├── claims_review/
│   │   │   ├── blueprint_creation/
│   │   │   │   └── index.py
│   │   │   ├── claims_review_agent_actions/
│   │   │   │   └── index.py
│   │   │   ├── create_vector_index/
│   │   │   │   └── index.py
│   │   │   ├── datasource_sync/
│   │   │   │   └── index.py
│   │   │   ├── invoke_data_automation/
│   │   │   │   ├── bda_wrapper.py
│   │   │   │   └── index.py
│   │   │   ├── invoke_verification/
│   │   │   │   ├── bedrock_agent_runtime_wrapper.py
│   │   │   │   └── index.py
│   │   │   ├── layer/
│   │   │   │   └── requirements.txt
│   │   │   └── manage_schema/
│   │   │       └── index.py
│   │   └── lending_flow/
│   │       ├── documents_post_processor/
│   │       │   └── index.py
│   │       ├── documents_processor/
│   │       │   └── index.py
│   │       ├── samples_post_processor/
│   │       │   └── index.py
│   │       └── samples_processor/
│   │           └── index.py
│   ├── requirements.txt
│   └── stacks/
│       ├── claims_review_stack/
│       │   ├── agent.py
│       │   ├── aurora_postgres.py
│       │   ├── document_automation.py
│       │   ├── knowledge_base.py
│       │   ├── prompts/
│       │   │   └── claims_review_agent.py
│       │   ├── schemas/
│       │   │   ├── claims_review_openapi.json
│       │   │   ├── create_database_schema.sql
│       │   │   └── delete_database_schema.sql
│       │   └── vector_store.py
├── README.md
├── source/
│   └── claims_review_app/
│       └── claims-cli.py
├── source.bat
```
</details>

## Setup Instructions

> [!Note]
>If you’re continuing this part from Installation part 1, you can skip step 1-4



1. Change to the `deployment` directory for the guidance repository <a name='deployment-directory'></a>
   ```
   cd guidance-for-intelligent-document-processing-using-amazon-bedrock/deployment
   ```
2. Create and activate a virtual environment:
   ```
   python -m venv .venv
   source .venv/bin/activate
   ```
3. Install required dependencies:
   ```
   pip install -r requirements.txt
   ```
4. Bootstrap AWS CDK (first-time only):
   ```
   cdk bootstrap
   ```
5. Go to the `layer` directory and install lambda layer dependencies into the `python` subdirectory:
   ```
   cd lambda/claims_review/layer/
   pip install -r requirements.txt --target python
   cd ../../..
   ```
  
6. Deploy the stack: <a name="deploy-the-stack"></a>
   ```
   cdk synth claims-review # Synthesize CloudFormation template
   cdk diff claims-review   # Review changes
   cdk deploy claims-review # Deploy stack
   ```

   To protect you against unintended changes that affect your security posture, the CDK CLI prompts you to approve security-related changes before deploying them. When prompted, review the changes and Enter `y` for  `Do you wish to deploy these changes (y/n)?` if you intend to proceed.

   Alternatively, in one command

   ```bash
   cdk deploy claims-review --require-approval never 
   ```
   Wait for the stack deploy to complete.

7. Check the stack status using the AWS CloudFormation service
   
   ```
    aws cloudformation describe-stacks --stack-name claims-review --query 'Stacks[0].StackStatus' --output text
   ```
  A successful initial deployment should show a 'CREATE_COMPLETE' status and a successful subsequent deployment should show
  'UPDATE_COMPLETE' status

## Using the Sample Application
See the guide [here](./b_claims_review_02_run_flow.md) for steps to run the claims review application
### 

## Security

The stack enforces the following security measures:

- The Bedrock Agent's Resource Role has the minimum permissions required to access the Foundation Model and invoke the Lambda function.
- The Lambda function's execution role has the basic execution permissions.
- The Lambda function is granted permission to be invoked by the Bedrock Agent.

## Troubleshooting <a name="Troubleshooting"></a>

If you encounter any issues during deployment or runtime, here are some troubleshooting steps:

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

### Deployment Issues:

#### General 
- Verify AWS credentials are configured correctly
- Ensure CDK is bootstrapped in your account/region
- Check the CloudFormation console for detailed error messages

#### `--app is required either in command-line, in cdk.json or in ~/.cdk.json`
Ensure you're in the right directory when running `cdk deploy`. see [Step 1](#deployment-directory)

### Runtime Issues:

- Check CloudWatch Logs for Lambda function errors
- Verify the IAM permissions are correct
- Ensure the Bedrock Agent and Action Group are configured correctly

**Common errors you might encounter:**

- "Resource not found": Ensure the required resources exist and the permissions are correct.
- "Access denied": Check the IAM roles and policies.
- "Invalid handler": Verify the Lambda function handler name.
- "Access denied when calling Bedrock": Verify Bedrock Model Access for the model used by the Agent in this case `amazon.titan-text-premier-v1:0`.

## Development

To modify the stack:

### Customize Stack Parameters <a name="customize_stack_parameters'></a>
The stack uses context values in `cdk.json` file to store default parameters used for stack creation. The values can be modified by modifying the `cdk.json`

### Customize the Claims Review Bedrock Agent prompt
The prompt instruction used to create the agent is in the `deployment/stacks/claims_review_stack/prompts/claims_review_agent.py`.
To Customize the agent instruction: 
1. Update the text set to variable `claims_review_agent_instruction`
2. save the changes
3. deploy the stack again using instructions in [6. Deploy the stack](#deploy-the-stack)

### Manage Action Group schema 
- The action group API schema used for the agent action group is in  `deployment/stacks/claims_review_stack/schemas/claims_review_openapi.json`
- The Lambda functions backing the action group APIs are in `deployment/lambda/claims_review/claims_review_agent_actions/index.py`.
- The Database schema for the claim database (Aurora Postgres Serverless) is in `deployment/stacks/claims_review_stack/schemas/create_database_schema.sql`

To Customize the action group API schema:
1. Update the api schema in the file using OpenAPI 3.0 format
2. If necessary, make changes to the action group labmda function. 
3. Make necessary changes to the database schema
3. Save all the changes
4. Deploy the stack again using instructions in [6. Deploy the stack](#deploy-the-stack)

> [!Important]
>In case of breaking/incompatible changes to the database schema, it might be neccesary to delete and redeploy the stack. Follow the steps in [Cleanup](#cleanup) and [6. Deploy the stack](#deploy-the-stack)


### Update stack resources
The `claims-review` stack has the following main source code files associated with it - 

- `deployment/stacks/claims_review_stack/agent.py` - The top-level `claims-review` stack that creates bedrock agent resources and uses custom construct to create and configure other related resources include the bedrock knowledge base, vector store, the aurora databaseand BDA automation.

- `deployment/stacks/claims_review_stack/vector_store.py` - Vector store resources include opensearch serverless collection and a Custom resource lambda function to create the vector index for the claims EoC knowledge base

- `deployment/stacks/claims_review_stack/knowledge_base.py` - A construct encapsulating resources required for the bedrock knowledge base including datasource buckets, datasources, the knowledge base itself and KB logging configuration


- `deployment/stacks/claims_review_stack/document_automation.py` - A construct encapsulating resources related to bedrock document automation, include the input/output s3 buckets, lambda function to invoke bda for insights

- `deployment/stacks/claims_review_stack/aurora_postgres.py` - Aurora Postgres database resources for the claims review database including, aurora cluster, database and initial schema creation

- `deployment/lambda/claims_review` - Function code for Lambda functions used in the claims-review stack. The main functions are - 
  - `deployment/lambda/claims_review/claims_review_agent_actions` - Bedrock Agent Action group API functions
  
  - `deployment/lambda/claims_review/create_vector_index` - Function to create the vector index as part of CDK deployment
  
  - `deployment/lambda/claims_review/datasource_sync` - Function to trigger Bedrock Knowledge Base datasource sync as new documents are uploaded to the backing datasource s3 bucket
  
  - `deployment/lambda/claims_review/invoke_data_automation` - function to trigger the BDA insight job after a new claim form is submitted

  - `deployment/lambda/claims_review/invoke_verification` - function to trigger claims review bedrock agent after the BDA insight job is completed and claim form data extracted output is available.

  - `deployment/lambda/claims_review/manage_schema` - function to create/update Aurora database schema as part of CDK deployment 

To update stack resources - 

1. Update the associated stack or construct file.
2. Update the Lambda function code in the respective directories, if necessary
3. Run `cdk diff claims-review` to review the changes.
4. Deploy the changes with `cdk deploy claims-review`.

## Cleanup  <a name="cleanup"></a>
 
1. Change to the `deployment` directory for the guidance repository
   ```
   cd guidance-for-intelligent-document-processing-using-amazon-bedrock/deployment
   ```
 
1. Destroy the stack
    ```bash
    cdk destroy claims-review
    ```

## Contributing

1. Create a new branch for features.
2. Update the documentation as needed.
3. Test the changes thoroughly.
4. Submit a pull request.

## Useful Links

- [AWS CDK Python Reference](https://docs.aws.amazon.com/cdk/api/v2/python/index.html)
- [AWS Lambda Developer Guide](https://docs.aws.amazon.com/lambda/latest/dg/welcome.html)
- [Amazon Bedrock Developer Guide](https://docs.aws.amazon.com/bedrock/latest/userguide/what-is-bedrock.html)
