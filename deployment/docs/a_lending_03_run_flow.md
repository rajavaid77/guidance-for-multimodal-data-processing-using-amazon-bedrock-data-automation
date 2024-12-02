# Instructions For Using Blueprints To Process Loan Applications

You have now completed the install and setup of the solution to process Loan Applications. Our deployed solution has the components shown. If you have not completed this step, please go back and complete the deployment steps [here](./deployment-readme.md) before proceeding. 

<img src="../assets/img/guidance-for-document-processing-using-amazon-bedrock-keystone-flow-1.png" width="800" />

After installing, we used BDA in the Amazon Console to view  to access five sample blueprints we need for processing loan applications. We then add a new blueprints for a Homeowners Insurance Application form. If you have not completed this step, please go back and complete the setup steps [here](./console-blueprint-instructions.md)


BDA is a generative-AI powered capability of Amazon Bedrock that enables you to automate your end-to-end Intelligent Document Processing (IDP) workflows quickly, accurately and at scale. A blueprint is a structural representation of your desired output for a specific document type (e.g. invoices, drivers licenses or IRS form 1099-INT). We then feed new unseen documents into the solution, for BDA to detect the document type, apply the correct blueprint and send the extracted results for downstream processing.


## Processing of a Lending Application Package

We will now submit a new lending application to BDA. The workflow will process the lending application package, identifying the six documents in the package, and applying the appropriate Blueprint for each document. 

1.  An Earning Statement (Pay Stub)
2.  A Check
3.  A drivers License
4.  A Bank Statement
5.  A W2 US Tax form
6.  A Homeowners Insurance Application

Steps:
1. Upload a new lending package to the S3 input bucket. 
2. Check for results in the S3 output bucket. 
3. Instructions to review and understand the results. 

We also need debug instructions (CloudWatch, Lamnda moniror, etc) of the expected results are not generated. 
