"""Read Cloud credentials without sending stored values to browser widgets."""

import os

import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError


def secret(name: str) -> str:
    value = os.environ.get(name, "")
    if value:
        return value.strip()
    try:
        return str(st.secrets.get(name, "")).strip()
    except (StreamlitSecretNotFoundError, FileNotFoundError):
        return ""
