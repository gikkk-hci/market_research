from datetime import timezone, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import quote
import xml.etree.ElementTree as ET

import requests
import streamlit as st


@st.cache_data(ttl=1800, show_spinner=False)
def headlines(query):
    url = f"https://news.google.com/rss/search?q={quote(query)}&hl=ko&gl=KR&ceid=KR:ko"
    try:
        response = requests.get(url, timeout=(5, 12))
        response.raise_for_status()
        root = ET.fromstring(response.content)
        articles = []
        for entry in root.findall("./channel/item")[:6]:
            try:
                published = parsedate_to_datetime(entry.findtext("pubDate", "")).astimezone(timezone(timedelta(hours=9))).strftime("%Y-%m-%d")
            except (ValueError, TypeError):
                published = "날짜 미상"
            articles.append({"title": entry.findtext("title", ""), "url": entry.findtext("link", ""), "date": published})
        return articles
    except (requests.RequestException, ET.ParseError):
        return []
