import boto3
import streamlit as st
from opensearchpy import OpenSearch, RequestsHttpConnection, AWSV4SignerAuth



auth = AWSV4SignerAuth(
    boto3.Session().get_credentials(),
    boto3.session.Session().region_name,
    "aoss"
)

aoss_client = OpenSearch(
    hosts=[{'host': "uva7tj85lcqs6yz6i1j7.us-east-1.aoss.amazonaws.com", 'port': 443}],
    http_auth=auth,
    use_ssl=True,
    verify_certs=True,
    connection_class=RequestsHttpConnection
)
st.markdown(aoss_client.indices.exists(index="claims_eoc_index"))