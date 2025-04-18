
import streamlit as st
from utils import get_claims_submission_bucket_name, get_claims_review_bucket_name
from botocore.exceptions import ClientError
import boto3
import pandas as pd
from utils import get_aurora_cluster_arn, get_aurora_database_name, get_aurora_secret_arn
from utils import show_pdf
import json

# Initialize S3 client
s3 = boto3.client('s3')
st.set_page_config(layout="wide")

def init_rds_data_client():
    """Initialize RDS Data API client"""
    return boto3.client('rds-data')

def execute_query(client, query, database, secret_arn, cluster_arn):
    """Execute SQL query using RDS Data API"""
    try:
        response = client.execute_statement(
            secretArn=secret_arn,
            database=database,
            resourceArn=cluster_arn,
            sql=query,
            includeResultMetadata=True
        )
        return response
    except ClientError as e:
        st.error(f"Error executing query: {e}")
        return None

    
def create_presigned_url(bucket_name, object_name, expiration=3600):
    """Generate a presigned URL to share an S3 object"""
    try:
        url = s3.generate_presigned_url('get_object',
                                            Params={'Bucket': bucket_name,
                                                    'Key': object_name},
                                            ExpiresIn=expiration)
    except ClientError as e:
        st.error(f"Error generating presigned URL: {e}")
        return None
    
    return url

def state_order(states):
    """Custom function to order states"""
    values = [str(val).strip().lower() for val in states if pd.notna(val)]
    if states.isin(['SUCCESS']).any():
        return "SUCCESS"
    elif states.isin(['IN PROGRESS']).all():
        return "IN PROGRESS"
    else:
        return "NOT STARTED"



def show_progress(df):

    try:
        # Assuming your dataframe is called 'df'
        # Create pivoted table
        pivoted_df = df.pivot_table(
            index='CLAIM REFERENCE',
            columns='EVENT',
            values='STATUS',
            aggfunc=state_order
        )

        # Fill NaN values with "NOT STARTED"
        pivoted_df = pivoted_df.fillna("NOT STARTED")
        pivoted_df = pivoted_df.reindex(columns=["CLAIM FORM SUBMISSION", "CLAIM DATA PROCESSING", "CLAIM VERIFICATION"])
        # Reset index but keep claim_reference as a regular column
        pivoted_df = pivoted_df.reset_index()
        
        # Remove the index name
        pivoted_df.columns.name = None

        # Define status symbols
        def status_to_symbol(status):
            if status == "SUCCESS":
                return "✅ SUCCESS"
            elif status == "IN PROGRESS":
                return "🔄 IN PROGRESS"
            else:
                return "⚪ NOT STARTED"

        # Apply the symbols
        for col in pivoted_df.columns:
            if col != 'CLAIM REFERENCE':
                pivoted_df[col] = pivoted_df[col].apply(status_to_symbol)

        pivoted_df["Report"] = pivoted_df["CLAIM REFERENCE"].apply(show_report)
        # Display in Streamlit without index
        #st.dataframe(pivoted_df, hide_index=True)  # For newer versions of Streamlit
        #st.table(pivoted_df)  # st.table automatically hides the index

        pivoted_df = pivoted_df.style.format({'Details': lambda x: f'<a href="{x}">Report</a>'})
        # Display the DataFrame with clickable links
        #st.write(pivoted_df.to_html(escape=False, index=False), unsafe_allow_html=True)
        
        df = st.dataframe(
            pivoted_df,
            column_config={
                "Report": st.column_config.LinkColumn(
                    "Details", display_text="Details"
                 )
            },  
            hide_index=True,
            use_container_width=True
        )
        
    except Exception as e:
        st.error(f"Error displaying progress: {e}") 

def format_results(response):
    """Format query results into a list of dictionaries"""
    if not response or 'records' not in response:
        return []
    records = response['records']
    formatted_results = []
    
    for record in records:
        row = {}
        for i, value in enumerate(record):
            # Get the first key-value pair from the value dictionary
            field_value = list(value.values())[0]
            column_name =response['columnMetadata'][i]['name']
            row[column_name] = field_value
        formatted_results.append(row)
    
    return formatted_results


def show_report(claim_reference):
    key = f'{claim_reference}/claim_output.json'
    if  check_s3_url_exists(get_claims_review_bucket_name(), key):
        url = f'?claim_reference={claim_reference}'
        return url
    

def show_all_claims():
    # Create a text area for SQL query input
    st.title("Claims Submissions")
    if st.button("🔄", key="refresh"):
        st.rerun()
    query = "SELECT id, claim_reference, claim_event, claim_status FROM claim_event"
    client = init_rds_data_client()
    with st.spinner("Loading claims..."):
        # Execute the query
        response = execute_query(
            client=client,
            query=query,
            database=get_aurora_database_name(),
            secret_arn=get_aurora_secret_arn(),
            cluster_arn=get_aurora_cluster_arn()
        )

        if response:
            # Format and display results
            results = format_results(response)
            if results:
                df = pd.DataFrame(results, columns=['id', 'claim_reference', 'claim_event', 'claim_status'])
                df.columns= ['CLAIM ID', 'CLAIM REFERENCE', 'EVENT', 'STATUS']
                show_progress(df)
            else:
                st.info("No claims found.")

def get_claim_form_uri(claim_reference):
    bucket_name = get_claims_submission_bucket_name()
    #get the first object from the bucket and key
    response = s3.list_objects_v2(Bucket=bucket_name, Prefix=claim_reference)
    if 'Contents' not in response:
        st.error(f"No objects found in {bucket_name}/{object_name}")
        return None
    # Get the first object from the list
    object_name = response['Contents'][0]['Key']

def get_claim_event_detail(result, event, status):
    event =  next((entry["detail"]
                for entry in result 
                if entry["claim_event"] == event 
                and entry["claim_status"] == status), '{}')
    return json.loads(event)

def get_json_from_s3_resource(bucket_name, file_key):
    try:
        # Create S3 resource
        s3 = boto3.resource('s3')
        
        # Get object
        obj = s3.Object(bucket_name, file_key)
        
        # Read and parse JSON
        json_content = json.loads(obj.get()['Body'].read().decode('utf-8'))
        return json_content
    except:
        return None

def show_claim(bucket_name, given_prefix):
        claim_reference = st.query_params["claim_reference"]
        st.title("View Claim Details - {}".format(claim_reference))
        query = "SELECT id, claim_reference, claim_event, claim_status, detail FROM claim_event where claim_reference = '{}'".format(claim_reference)
        client = init_rds_data_client()
        with st.spinner("Loading claims..."):
            # Execute the query
            response = execute_query(
                client=client,
                query=query,
                database=get_aurora_database_name(),
                secret_arn=get_aurora_secret_arn(),
                cluster_arn=get_aurora_cluster_arn()
            )

            if response:
                # Format and display results
                results = format_results(response)
                bda_event = get_claim_event_detail(results, "CLAIM DATA PROCESSING", "SUCCESS")
                input_s3_object = bda_event.get('detail',{}).get("input_s3_object", {}).get('name')
                pdf_content = show_pdf(file_path=create_presigned_url(bucket_name, input_s3_object ))
                pdf_display = f'<iframe src="data:application/pdf;base64,{pdf_content}" width="800" height="800" type="application/pdf"></iframe>'
                st.markdown("#### Claim Form")
                form_view, json_view = st.columns([2,1])
                with form_view:
                    st.markdown(pdf_display, unsafe_allow_html=True)
                with json_view:
                    with st.container(height=800):
                        json = get_json_from_s3_resource(get_claims_review_bucket_name(), f'{input_s3_object}.json')
                        # Display the raw JSON data (for debugging)
                        st.write("JSON Structure:", json)

                st.markdown("#### Claim Verification Report")
                s3_markdown(get_claims_review_bucket_name(), f"{claim_reference}/claim_output.json")


def check_s3_url_exists(bucket_name, key):
    s3_client = boto3.client('s3')
    try:
        s3_client.head_object(Bucket=bucket_name, Key=key)
        return True
    except ClientError as e:
        if e.response['Error']['Code'] == '404':
            return False
        else:
            raise

def s3_markdown(bucket_name, file_key):
    try:
        s3_client = boto3.client('s3')
        response = s3_client.get_object(Bucket=bucket_name, Key=file_key)
        content = response['Body'].read().decode('utf-8')
        content = content.strip('"')
        content = content.replace('\\n', '  \n')
        st.markdown(content, unsafe_allow_html=True)

    except Exception as e:
        st.error(f"Error reading from S3: {str(e)}")


def main():

    # Get bucket name from user input
    bucket_name = get_claims_submission_bucket_name()

    try:
        if "claim_reference" in st.query_params and st.query_params["claim_reference"]:
            show_claim(bucket_name, st.query_params["claim_reference"])            
        else:
            show_all_claims()
    
    except Exception as e:
        st.markdown(f"Error listing prefixes: {str(e)}")

main()