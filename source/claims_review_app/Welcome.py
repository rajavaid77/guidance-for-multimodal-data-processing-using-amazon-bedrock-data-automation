import streamlit as st
import boto3
import json
import time
#set page width

pages = {
    "Welcome": [
        st.Page("views/main.py", title="Main")
    ],
    "Claims Submission": [
        st.Page("views/02_Submit_New_Claim.py", title="Submit New Claim"),
        st.Page("views/04_View_Claims_Submission.py", title="View Claim Submissions")
    ],
    "Claims Admin": [
        st.Page("views/01_Ingest_Evidence_Of_Coverage.py", title="Upload Evidence of Coverage"),
        #st.Page("views/07_View_KB_Documents.py", title="View KnowledgeBase Documents"),
        #st.Page("views/05_Test_Vector_Index.py", title="Manage Vector Index"),
        #st.Page("views/06_View_Bounding_Box.py", title="Bounding Box"),
    ]
}

pg = st.navigation(pages)
pg.run()