import streamlit as st
import boto3
from botocore.exceptions import ClientError
from utils import get_eoc_knowledge_base_id

bedrock_agent_runtime_client = boto3.client(service_name='bedrock-agent-runtime')
bedrock_agent_client = boto3.client(service_name='bedrock-agent')

def retrieve_documents(kb_id, query, max_results=10):
    try:
        response = bedrock_agent_runtime_client.retrieve(
            knowledgeBaseId=kb_id,
            retrievalQuery=query,
            maxResults=max_results
        )
        
        return response['retrievalResults']
    except ClientError as e:
        st.error(f"Error retrieving documents: {str(e)}")
        return []

def get_kb_documents(kb_id, datasource_id):
    try:
        response = bedrock_agent_client.get_knowledge_base_documents(
            knowledgeBaseId=kb_id,
            datasourceId=datasource_id
        
        )
    except ClientError as e:
        st.error(f"Error retrieving documents: {str(e)}")
        return None

def main():
    st.title("Bedrock Knowledge Base Document Viewer")
    
    bedrock_agent_client.get_kb(get_eoc_knowledge_base_id())


    # Input for Knowledge Base ID
    kb_id = st.text_input("Enter Knowledge Base ID")
    
    # Input for search query
    query = st.text_input("Enter search query")
    
    # Number of results slider
    max_results = st.slider("Maximum number of results", 1, 20, 10)
    
    if st.button("Search Documents"):
        if kb_id and query:
            with st.spinner("Retrieving documents..."):
                documents = retrieve_documents(kb_id, query, max_results)
                
                if documents:
                    for i, doc in enumerate(documents, 1):
                        with st.expander(f"Document {i} (Score: {doc['score']:.2f})"):
                            st.write("Location:", doc['location'])
                            st.write("Content:", doc['content'])
                else:
                    st.warning("No documents found.")
        else:
            st.warning("Please enter both Knowledge Base ID and search query.")


main()
