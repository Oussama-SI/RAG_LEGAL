

def init_state(st):
    defaults = {
        'chroma_client': None,
        'collection': None,
        'embed_model': None,
        'kaggle_api_url': '',
        'kaggle_status': {},
        'indexed_files': [],
        'last_contract': '',
        'last_contract_type': '',
        'last_metrics': {},
        'generation_history': [],
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v