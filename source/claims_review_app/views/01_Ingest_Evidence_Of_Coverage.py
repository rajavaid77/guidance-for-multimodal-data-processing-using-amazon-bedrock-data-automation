import streamlit as st
import requests
import boto3
from utils import get_claims_eoc_bucket_name
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
        'name': 'EOC - AnyHealth Standard',
        'file_name': 'Evidence_of_Coverage_-_AnyHealth_Standard.pdf',
        #'download_url': 'https://raw.githubusercontent.com/aws-solutions-library-samples/guidance-for-multimodal-data-processing-using-amazon-bedrock-data-automation/main/assets/data/claims_review/cms_1500/sample3_cms-1500-P.pdf'
        'download_url':  'https://raw.githubusercontent.com/rajavaid77/guidance-for-multimodal-data-processing-using-amazon-bedrock-data-automation/refs/heads/rajavaid-fix-sample-claim-forms/assets/data/claims_review/eoc/Evidence_of_Coverage_-_AnyHealth_Standard.pdf'
    },
    {
        'name':  'EOC - AnyHealth Plus',
        'file_name': 'Evidence_of_Coverage_-_AnyHealth_Plus.pdf',
        #'download_url': 'https://raw.githubusercontent.com/aws-solutions-library-samples/guidance-for-multimodal-data-processing-using-amazon-bedrock-data-automation/main/assets/data/claims_review/cms_1500/sample1_cms-1500-P.pdf'
        'download_url':  'https://raw.githubusercontent.com/rajavaid77/guidance-for-multimodal-data-processing-using-amazon-bedrock-data-automation/refs/heads/rajavaid-fix-sample-claim-forms/assets/data/claims_review/eoc/Evidence_of_Coverage_-_AnyHealth_Plus.pdf'
    },
    {
        'name': 'EOC - AnyHealth Premium',
        'file_name': 'Evidence_of_Coverage_-_AnyHealth_Premium.pdf',
        #'download_url': 'https://raw.githubusercontent.com/aws-solutions-library-samples/guidance-for-multimodal-data-processing-using-amazon-bedrock-data-automation/main/assets/data/claims_review/cms_1500/sample2_cms-1500-P.pdf'
        'download_url':  'https://raw.githubusercontent.com/rajavaid77/guidance-for-multimodal-data-processing-using-amazon-bedrock-data-automation/refs/heads/rajavaid-fix-sample-claim-forms/assets/data/claims_review/eoc/Evidence_of_Coverage_-_AnyHealth_Premium.pdf'
    }
]

#function to generate custom unique Id
def generate_unique_id():
    code = ''.join(random.choices(string.ascii_letters + string.digits, k=6))
    return code

def upload_to_s3(file_url, file_name):
    try:
        # Use session for requests
        with session.get(file_url, stream=True) as response:
            response.raise_for_status()
            s3_client.upload_fileobj(
                response.raw,
                get_claims_eoc_bucket_name(),
                f"{file_name}"
            )
    except (requests.RequestException, boto3.exceptions.S3UploadFailedError) as e:
        st.error(f"Error uploading file: {str(e)}")
        return False


def main():
    #files = get_github_files()
    st.title("Submit Evidence of Coverage Documents")

    files= sample_docs

    if files:
        #Create table header
        col1, col2 = st.columns([2, 3])

        with col1:
            st.markdown("#### Sample Claim EoC Documents")
            # Single radio button group for all rows
            selected_file_name = st.radio(
                "Select a document to upload",
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
