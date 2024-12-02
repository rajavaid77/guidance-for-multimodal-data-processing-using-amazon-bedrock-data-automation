# Intelligent Document Processing with Amazon Bedrock Data Automation

Automate document processing using AWS AI/ML services to:
- Speed up business processes
- Improve decision quality 
- Reduce operational costs
- Free up expert resources for high-value tasks

This solution uses Amazon Bedrock's Generative AI capabilities to:
1. Classify documents
2. Extract content
3. Process information using foundation models

<details>
  <summary>Note on dataset and Acceptable End User Policy from the model provider</summary>

The dataset utilized in this guidance consists entirely of synthetic data. This artificial data is designed to mimic real-world information but does not contain any actual personal or sensitive information.

For use cases related to finance and medical insurance as used in this guidance:

Users must adhere to the model provider's Acceptable Use Policy at all times. This policy governs the appropriate use of the synthetic data and associated models, and compliance is mandatory.This synthetic data is provided for testing, development, and demonstration purposes only. It should not be used as a substitute for real data in making financial or medical decisions affecting individuals or organizations.
By using this dataset and guidance, you acknowledge that you have read, understood, and agree to comply with all applicable terms, conditions, and policies set forth by the model provider.

</details>

## Table of Contents

- [Key Features](#key-features)
  - [Part A: Automated Lending Flow](#part-a-automated-lending-flow)
  - [Part B: Intelligent Claims Review](#part-b-intelligent-claims-review)
- [Getting Started](#getting-started)
  - [Prerequisites](#prerequisites)
  - [Quick Start Guide](#quick-start-guide)
- [Cost Estimation](#cost-estimation)
- [Important Notes](#important-notes)
- [Support & Documentation](#support--documentation)
- [Legal Notice](#legal-notice)
- [Contributors](#contributors)

## Key Features

### Part A: Automated Lending Flow
- Uses Amazon Bedrock Data Automation (BDA) for document processing
- Creates reusable document blueprints
- Automatically detects document types
- Extracts relevant information
- Processes results downstream

### Part B: Intelligent Claims Review
- Processes insurance documents
- Stores extracted content in Bedrock Knowledge Base
- Uses RAG (Retrieval Augmented Generation) for accurate responses
- Employs Bedrock Agent to determine claim eligibility
- Updates claims database automatically

## Getting Started

### Prerequisites
1. Active AWS Account ([Create one here](https://aws.amazon.com/resources/create-account/))
2. AWS CLI ([Installation guide](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html))
3. AWS CDK CLI ([Installation guide](https://docs.aws.amazon.com/cdk/v2/guide/getting_started.html))

### Quick Start Guide

#### Lending Flow Setup
1. [Deploy lending flow stack](deployment/docs/a_lending_01_deployment.md)
2. [Configure BDA project & blueprints](deployment/docs/a_lending_02_setup_blueprints.md)
3. [Process lending documents](deployment/docs/a_lending_03_run_flow.md)

#### Claims Review Setup
1. [Create BDA blueprint](deployment/docs/b_claims_review_03_create_blueprint.md)
2. [Deploy claims review stack](deployment/docs/b_claims_review_01_deploy.md)
3. [Process claims](deployment/docs/b_claims_review_02_run_flow.md)

## Cost Estimation
- Approximate cost: $XX/month for 1,000 pages (US East Region, December 2024)
- Recommend setting up [AWS Budget](https://docs.aws.amazon.com/cost-management/latest/userguide/budgets-managing-costs.html)

### Cost Breakdown
| Service | Usage | Cost (USD) |
|---------|--------|------------|
| Bedrock Data Automation | 1,000 docs | $XX |
| Bedrock Knowledge Base | 1,000 docs/month | $XX |
| Bedrock Agent | 1,000 transactions | $XX |
| Lambda | 3,000 requests | $0.19 |
| EventBridge | 3,000 events | $XX |
| S3 Storage | 10 GB/month | $0.24 |
| Aurora | 1,000 images | $XX |

## Important Notes

### Data Usage
- Solution uses synthetic data only
- No real personal/sensitive information included
- For testing/development purposes only

### Regional Availability
Available in regions supporting:
- Amazon Bedrock
- Bedrock Data Exchange
- Bedrock Agents
- Supporting AWS services

### Service Quotas
- Works within default AWS service quotas
- Some quotas can be increased on request
- Monitor usage via CloudWatch
- Set up alerts for quota limits

## Support & Documentation
- [Service Documentation](link)
- [Troubleshooting Guide](link)
- [FAQ](link)

## Legal Notice
AWS provides this solution "as is" without warranties. Users are responsible for compliance with model provider policies and applicable regulations.

## Contributors
[List of contributors]

