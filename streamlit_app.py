"""Streamlit Community Cloud entrypoint for the existing team portal."""

import streamlit as st


st.set_page_config(page_title="AI 업무지원 통합 포털", page_icon="📊", layout="wide")
st.iframe("/app/static/portal.html", height=1000, alt="AI 업무지원 통합 포털")
