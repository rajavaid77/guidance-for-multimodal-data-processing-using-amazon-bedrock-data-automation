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

4. In the Create blueprint screen, select upload from computer, then click `Choose file`.
   ![create_blueprint_view][screenshot_create_blueprint_view]

5. Browse to the sample CMS 1500 form at `assets/data/claims_review/cms_1500/sample1_cms-1500-P.pdf` in your clone of the repo in your local computer, then select the file and choose open.

6. Verify the document preview and click `Upload`. If you see a `Create bucket confirmation` then click `Confirm` to confirm creation of bucket.  BDA creates an S3 bucket in your AWS Account. This would be used to store user assets
   ![upload_blueprint_sample][screenshot_upload_blueprint_view]

7. Once the sample is uploaded, the Generate Blueprint button is enabled. You can optionally provide a prompt to create a blueprint.  If you do not provide a prompt the Blueprint prompt AI will instead generate one.
   ![screenshot_blueprint_prompt][screenshot_blueprint_prompt]

8. Click on `Generate Blueprint` to start the BDA blueprint creation process. BDA will analyze the sample document to find any matching blueprint from sample blueprints global catalog 
   ![screenshot_generate_blueprint][screenshot_generate_blueprint]

9. When BDA has no matches from global catalog, BDA presents a `Create a blueprint` pop-up. In the pop-up box, under `Blueprint name`, Enter `claims-review-cms-1500` and click `Create Blueprint` to start the BDA job to extract keys, values from the sample document to create a blueprint.
   ![name_blueprint][screenshot_name_blueprint]

> [!Important]
>By default the claims review stack uses the blueprint name `claims-review-cms-1500`. To use another name you would need to use add a `blueprint_name:<<your_chosen_blueprint_name` to the --context parameter when running the `cdk deploy` command for the stack. See [Customize Stack Parameters](b_claims_review_01_deploy.md#customize_stack_parameters)


## Step 3: Review and Refine the Blueprint

1. Once BDA has extracted the fields and values, you can view them in Blueprint `Extractions` section. You might see various sections including:
   - Patient and Insured Information
   - Physician or Supplier Information
   - Diagnosis Codes
   - Service Lines (potentially multiple)
> [!Note]
>Your `Extractions` output may vary depending on if your entered a `Blueprint prompt` or based on the `AI Generated prompt for the current blueprint` 


   ![Extracted_fields][screenshot_extracted_fields]

2. Click `Save and exit blueprint prompt` to save the blueprint along with the `Extractions` schema
![Save_Blueprint][screenshot_save_blueprint]


## Step 4: Refine and Iterate
1. Once the blueprint is create, you can manually refine the Blueprint in the `Blueprint` section of the page.
2. You can add / update the extracted fields.
3. Click `Save blueprint` to save the blueprint or `Publish a new version`
![Save_Blueprint][screenshot_save_blueprint]

4. Once the blueprint is saved, you can also upload other sample documents and get results using the newly create blueprint
5. Click `Download` to download the results to your local computer and review the extracted values along with confidence and explainability info
6. If necessary, return to the blueprint and make adjustments:
   - Add missing fields
   - Refine field names for clarity
   - Adjust the initial prompt if certain areas need more attention
7 Repeat the testing process with various CMS 1500 forms to ensure consistency and accuracy
8. Finally, you can save the blueprint


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