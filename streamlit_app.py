"""Streamlit entrypoint for the existing team portal."""

from pathlib import Path

import streamlit as st


st.set_page_config(page_title="AI 업무지원 통합 포털", page_icon="📊", layout="wide")

portal_path = Path(__file__).resolve().parent / "static" / "portal.html"
if not portal_path.is_file():
    st.error("static/portal.html 파일이 없습니다. GitHub 업로드 경로를 확인해 주세요.")
    st.stop()

# Community Cloud embeds the app below its own URL prefix (e.g. /~/+/).
# srcdoc inherits that app's base URL, so the relative iframe src keeps the
# static route under the actual app on both Cloud and localhost. Loading the
# portal as a document also preserves its existing hash/history navigation.
st.iframe(
    """<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <style>
    html, body { margin: 0; height: 100%; }
    iframe { display: block; width: 100%; height: 100%; border: 0; }
  </style>
</head>
<body>
  <iframe src="app/static/portal.html" title="AI 업무지원 통합 포털"></iframe>
</body>
</html>""",
    height=1000,
    alt="AI 업무지원 통합 포털",
)
