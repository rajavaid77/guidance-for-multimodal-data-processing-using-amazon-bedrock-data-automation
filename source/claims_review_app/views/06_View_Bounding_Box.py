import streamlit as st
import json
import pandas as pd
from typing import Any, Dict, List
import uuid

def is_tabular_data(data: Any) -> bool:
    """Check if data should be displayed as a table"""
    if isinstance(data, list):
        # Check if list contains dictionaries
        return all(isinstance(item, dict) for item in data)
    return False

def flatten_dict(d: Dict, parent_key: str = '', sep: str = '.') -> Dict:
    """Flatten nested dictionary with custom separator"""
    items: List = []
    for k, v in d.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else k
        if isinstance(v, dict):
            items.extend(flatten_dict(v, new_key, sep=sep).items())
        elif not isinstance(v, list):
            items.append((new_key, v))
    return dict(items)

def create_clickable_cell(value: Any, key: str) -> None:
    """Create a clickable cell with consistent styling"""
    if st.button(str(value), key=key):
        st.session_state.selected_field = key
        st.session_state.selected_value = value

def display_table(data: List[Dict], parent_key: str = '') -> None:
    """Display tabular data with clickable cells"""
    if not data:
        return

    df = pd.DataFrame(data)
    st.markdown("### Table View")
    
    # Display column headers
    cols = st.columns(len(df.columns))
    for i, col_name in enumerate(df.columns):
        with cols[i]:
            st.markdown(f"**{col_name}**")

    # Display rows with clickable cells
    for idx, row in df.iterrows():
        cols = st.columns(len(df.columns))
        for i, (col_name, value) in enumerate(row.items()):
            with cols[i]:
                cell_key = f"{parent_key}_{col_name}_{idx}_{uuid.uuid4()}"
                create_clickable_cell(value, cell_key)

def display_key_value_pairs(data: Dict) -> None:
    """Display flattened key-value pairs"""
    st.markdown("### Key-Value Pairs")
    
    # Flatten the dictionary excluding lists
    flat_data = flatten_dict(data)
    
    # Display each key-value pair
    for key, value in flat_data.items():
        col1, col2 = st.columns([1, 2])
        with col1:
            if st.button(key, key=f"key_{key}_{uuid.uuid4()}"):
                st.session_state.selected_field = key
                st.session_state.selected_value = value
        with col2:
            st.write(str(value))

def process_json_structure(data: Any, parent_key: str = '') -> None:
    """Recursively process JSON structure and identify tabular data"""
    if isinstance(data, dict):
        for key, value in data.items():
            new_key = f"{parent_key}_{key}" if parent_key else key
            if is_tabular_data(value):
                st.markdown(f"## {key}")
                display_table(value, new_key)
            elif isinstance(value, dict):
                process_json_structure(value, new_key)
            elif isinstance(value, list):
                if all(isinstance(item, (str, int, float, bool)) for item in value):
                    st.markdown(f"### {key}")
                    st.write(value)
                else:
                    process_json_structure(value, new_key)

def main():
    st.title("JSON Data Viewer")
    
    # Initialize session state
    if 'selected_field' not in st.session_state:
        st.session_state.selected_field = None
    if 'selected_value' not in st.session_state:
        st.session_state.selected_value = None
    
    # File uploader for JSON data
    uploaded_file = st.file_uploader("Upload JSON file", type=['json'])
    
    if uploaded_file is not None:
        try:
            json_data = json.load(uploaded_file)
        except json.JSONDecodeError:
            st.error("Invalid JSON file")
            return
    else:
        # Use example JSON data if no file is uploaded
        try:
            json_data = {
                # Your JSON data here
            }
        except Exception as e:
            st.error(f"Error loading JSON data: {str(e)}")
            return

    # Create tabs
    tab1, tab2 = st.tabs(["Key-Value View", "Table View"])
    
    with tab1:
        display_key_value_pairs(json_data)
    
    with tab2:
        process_json_structure(json_data)
    
    # Display selected field information
    if st.session_state.selected_field:
        st.sidebar.markdown("### Selected Field")
        st.sidebar.write(f"Field: {st.session_state.selected_field}")
        st.sidebar.write(f"Value: {st.session_state.selected_value}")
        # Here you would add logic to draw bounding box on PDF
        
main()
