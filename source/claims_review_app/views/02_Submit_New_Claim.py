import streamlit as st
import requests
import boto3
from utils import get_claims_submission_bucket_name
import pandas as pd
from io import BytesIO
import random, string
from utils import show_pdf
# AWS Config

s3_client = boto3.client('s3')
st.set_page_config(layout="wide")

# Add session management for requests
session = requests.Session()

sample_docs = [
    {
        'name': 'CMS 1500 Sample 1',
        'file_name': 'sample1_cms-1500-P.pdf',
        'download_url': 'https://raw.githubusercontent.com/aws-solutions-library-samples/guidance-for-multimodal-data-processing-using-amazon-bedrock-data-automation/main/assets/data/claims_review/cms_1500/sample1_cms-1500-P.pdf'
        #'download_url':  'https://raw.githubusercontent.com/rajavaid77/guidance-for-multimodal-data-processing-using-amazon-bedrock-data-automation/refs/heads/rajavaid-fix-sample-claim-forms/assets/data/claims_review/cms_1500/sample1_cms-1500-P.pdf'
    },
    {
        'name': 'CMS 1500 Sample 2',
        'file_name': 'sample2_cms-1500-P.pdf',
        'download_url': 'https://raw.githubusercontent.com/aws-solutions-library-samples/guidance-for-multimodal-data-processing-using-amazon-bedrock-data-automation/main/assets/data/claims_review/cms_1500/sample2_cms-1500-P.pdf'
        #'download_url':  'https://raw.githubusercontent.com/rajavaid77/guidance-for-multimodal-data-processing-using-amazon-bedrock-data-automation/refs/heads/rajavaid-fix-sample-claim-forms/assets/data/claims_review/cms_1500/sample2_cms-1500-P.pdf'
    },
    {
        'name': 'CMS 1500 Sample 3',
        'file_name': 'sample3_cms-1500-P.pdf',
        'download_url': 'https://raw.githubusercontent.com/aws-solutions-library-samples/guidance-for-multimodal-data-processing-using-amazon-bedrock-data-automation/main/assets/data/claims_review/cms_1500/sample3_cms-1500-P.pdf'
        #'download_url':  'https://raw.githubusercontent.com/rajavaid77/guidance-for-multimodal-data-processing-using-amazon-bedrock-data-automation/refs/heads/rajavaid-fix-sample-claim-forms/assets/data/claims_review/cms_1500/sample3_cms-1500-P.pdf'
    }
]

#function to generate custom unique Id
def generate_unique_id():
    code = ''.join(random.choices(string.ascii_letters + string.digits, k=6))
    return code

def upload_to_s3(file_url, file_name):
    claim_reference_id = generate_unique_id()
    try:
        # Use session for requests
        with session.get(file_url, stream=True) as response:
            response.raise_for_status()
            s3_client.upload_fileobj(
                response.raw,
                get_claims_submission_bucket_name(),
                f"{claim_reference_id}/{file_name}"
            )
        return claim_reference_id
    except (requests.RequestException, boto3.exceptions.S3UploadFailedError) as e:
        st.error(f"Error uploading file: {str(e)}")
        return False

    
def upload_to_s3_old(file_url, file_name):
    claim_reference_id = generate_unique_id()

    try:        
        # Download file from URL
        response = requests.get(file_url)
        file_content = BytesIO(response.content)
        
        # Upload to S3
        s3_client.upload_fileobj(file_content, get_claims_submission_bucket_name(), f"{claim_reference_id}/{file_name}")
        return claim_reference_id
    except Exception as e:
        st.error(f"Error uploading file: {str(e)}")
        return False




def main():
    #files = get_github_files()
    st.header("Submit Claim", divider=True)

    files= sample_docs

    if files:
        #Create table header
        col1, col2 = st.columns([1, 3])

        with col1:
            st.markdown("#### Sample Claim Forms")
            # Single radio button group for all rows
            selected_file_name = st.radio(
                "Select a form to upload",
                options=[doc['name'] for doc in files],
                index=None
            )
            # Upload button
            if st.button("Upload",type="primary", disabled=(selected_file_name is None)):
                if selected_file_name is not None:
                    selected_file = next((file for file in files if file['name'] == selected_file_name), None)
                    file_name = selected_file['file_name']
                    file_url = selected_file['download_url']
                    with st.spinner('Uploading file...'):
                        if claim_reference_id:= upload_to_s3(file_url, file_name):
                            claim_link = f"View_Claims_Submission?claim_reference={claim_reference_id}"
                            st.success(
                                f"Claim Submitted. Your Unique Claim Reference Id is "
                                f"[{claim_reference_id}]({claim_link})"
                            )
                        else:
                            st.error("Upload failed")
                else:
                    st.warning("Please select a file to upload")            
        with col2:
            # Display PDF preview
            st.markdown("#### PDF Preview")
            if(selected_file_name):
                # Use dictionary comprehension for faster lookup
                file_map = {doc['name']: doc for doc in files}
                selected_file = file_map.get(selected_file_name)
                if selected_file:
                    pdf_content = show_pdf(selected_file['download_url'])
                    st.markdown(
                        f'<iframe src="data:application/pdf;base64,{pdf_content}" width="800" height="700" type="application/pdf"></iframe>',
                        unsafe_allow_html=True
                    )
            else:
                st.write('Please select a sample for to preview')


main()
