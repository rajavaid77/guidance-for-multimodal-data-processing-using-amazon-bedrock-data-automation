# Instructions to create a Custom Blueprint for CMS 1500 Medical Claim Form in AWS Bedrock Document Automation

In this guide, we will create a custom blueprint for processing CMS 1500 medical claim forms using AWS Bedrock Document Automation (BDA). The CMS 1500 form is widely used for submitting medical claims to insurance providers in the United States.

## Step 1: Prepare Sample Document

To create a blueprint, you need to obtain a sample CMS 1500 filled form. You can find some samples in `assets/data/claims_review/cms_1500` folder of the repository.

## Step 2: Navigate to Bedrock Data Automation and Trigger Blueprint Generation

1. Navigate to the AWS Console
2. Search for "Bedrock" in the "Services" search bar and click 'Amazon Bedrock' in the search results
3. In the Bedrock console, click on the "Custom output setup" menu under Data Automation
   ![navigate_custom_output_setup][screenshot_nav_to_custom_output_setup]

3. In the Custom output setup screen, click on "Create Blueprint"
   ![navigate_create_blueprint][screenshot_nav_to_create_blueprint]

4. In the Create blueprint screen, select upload from computer, then click choose file.
   ![create_blueprint_view][screenshot_create_blueprint_view]

5. Browse to the sample CMS 1500 form at `assets/data/claims_review/cms_1500/sample1_cms-1500-P.pdf` in your clone of the repo in your local computer, then select the file and choose open.

6. Verify the document preview and click upload. BDA creates an S3 bucket, if one doesn't exists already for bda, in your account to save the file.
   ![upload_blueprint_sample][screenshot_upload_blueprint_view]

7. Once the sample is uploaded, the Generate Blueprint button is enable. You can optionally provide a prompt to create a blueprint.  If you do not provide a prompt the Blueprint prompt AI will instead generate one.
   ![screenshot_blueprint_prompt][screenshot_blueprint_prompt]

8. Click on `Generate Blueprint` to start the BDA blueprint creation process. BDA will analyze the sample form and create a new reusable Blueprint for future CMS 1500 forms.
   ![screenshot_generate_blueprint][screenshot_generate_blueprint]

9. Once the blueprint is ready, BDA prompts for a Blueprint name. Enter `claims-review-cms-1500` and click `Create Blueprint`. In a short while BDA would gather insights from the extract fields for the blueprint
   ![name_blueprint][screenshot_name_blueprint]

> [!Important]
>By default the claims review stack uses the blueprint name `claims-review-cms-1500`. To use another name you would need to modify the cdk context variable in `cdk.json` and redeploy the stack. See [Customize Stack Parameters](b_claims_review_01_deploy.md#customize-stack-parameters-a-namecustomize_stack_parameters)


## Step 3: Review and Refine the Blueprint

1. Review the extracted fields. You might see various sections including:
   - Patient and Insured Information
   - Physician or Supplier Information
   - Diagnosis Codes
   - Service Lines (potentially multiple)
   ![Extracted_fields][screenshot_extracted_fields]
2. If needed, manually add or adjust fields to ensure all critical information is captured


## Step 4: Refine and Iterate

1. Review the results of your test
2. If necessary, return to the blueprint and make adjustments:
   - Add missing fields
   - Refine field names for clarity
   - Adjust the initial prompt if certain areas need more attention
3. Repeat the testing process with various CMS 1500 forms to ensure consistency and accuracy
4. Finally, you can save the blueprint
![Save_Blueprint][screenshot_save_blueprint]

By following these steps, you'll have created a custom blueprint in AWS Bedrock Document Automation specifically designed to extract key information from CMS 1500 medical claim forms. This blueprint can be used to process large volumes of claims efficiently, supporting tasks such as claims processing, auditing, and data analysis in healthcare administration.

[screenshot_nav_to_custom_output_setup]: ../../assets/screenshots/claims_review_docs/navigate-to-bda.jpg
[screenshot_nav_to_create_blueprint]: ../../assets/screenshots/claims_review_docs/create-blueprint.jpg
[screenshot_create_blueprint_view]: ../../assets/screenshots/claims_review_docs/create-blueprint-view.jpg
[screenshot_upload_blueprint_view]: ../../assets/screenshots/claims_review_docs/upload-blueprint-sample.jpg
[screenshot_blueprint_prompt]: ../../assets/screenshots/claims_review_docs/blueprint-prompt.jpg
[screenshot_generate_blueprint]: ../../assets/screenshots/claims_review_docs/generate-blueprint.jpg
[screenshot_name_blueprint]: ../../assets/screenshots/claims_review_docs/name-blueprint.jpg
[screenshot_extracted_fields]: ../../assets/screenshots/claims_review_docs/extracted_fields.jpg
[screenshot_save_blueprint]: ../../assets/screenshots/claims_review_docs/save_blueprint.jpg