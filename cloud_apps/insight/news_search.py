from __future__ import annotations

from datetime import date
from html import unescape
import re
from urllib.parse import quote_plus
import xml.etree.ElementTree as ET

import requests

from cloud_apps.insight.insight_core import Source, normalize
from cloud_apps.insight.source_loader import deduplicate

# 검색 가능한 주제와 PDF 텍스트에서 확인할 표현
SEARCH_TOPICS = {
    "주거 부동산": ("주거", "주택", "아파트", "부동산", "전세", "월세", "분양", "부동산PF"),
    "NPL": ("NPL", "부실채권", "연체", "부도", "회수율", "대손", "충당금"),
    "기업금융": ("기업금융", "기업대출", "여신", "차주", "회사채", "조달", "기업부실"),
    "해외투자": ("해외투자", "해외법인", "국가위험", "외화", "환율", "투자손실"),
    "산업재 차량": ("산업재", "상용차", "건설기계", "트럭", "차량", "중고차", "담보가치"),
    "환율·금리": ("환율", "금리", "기준금리", "외환", "원화", "달러", "통화정책"),
}

def quarter_dates(period: str) -> tuple[str, str]:
    match = re.search(r"(20\d{2})\D*([1-4])\s*분기", period)
    if not match:
        match = re.search(r"(20\d{2})\s*Q([1-4])", period, re.I)
    if not match:
        raise ValueError("분기 기간을 확인할 수 없습니다.")
    year, quarter = int(match.group(1)), int(match.group(2))
    start_month = 1 + (quarter - 1) * 3
    start = date(year, start_month, 1)
    if quarter == 4:
        end = date(year + 1, 1, 1)
    else:
        end = date(year, start_month + 3, 1)
    return start.isoformat(), end.isoformat()

def search_related_news(pdf_texts: list[str], period: str, limit_per_topic: int = 5) -> tuple[list[Source], list[str]]:
    """Search Google News RSS using topics explicitly found in the supplied PDF text."""
    detected = []
    merged = " ".join(pdf_texts).lower()
    for topic, terms in SEARCH_TOPICS.items():
        if any(term.lower() in merged for term in terms):
            detected.append((topic, terms))
    if not detected:
        return [], ["PDF에서 사전 정의된 검색 주제를 찾지 못했습니다."]
    start, end = quarter_dates(period)
    results, errors = [], []
    for topic, terms in detected:
        matched = [term for term in terms if term.lower() in merged]
        query_terms = matched[:3] or [topic]
        query = f'({" OR ".join(query_terms)}) 금융 시장 after:{start} before:{end}'
        url = "https://news.google.com/rss/search?q=" + quote_plus(query) + "&hl=ko&gl=KR&ceid=KR:ko"
        try:
            response = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0 MarketInsightPoC/1.0"})
            response.raise_for_status()
            root = ET.fromstring(response.content)
            for item in root.findall("./channel/item")[:limit_per_topic]:
                title = normalize(item.findtext("title", default=""))
                link = normalize(item.findtext("link", default=""))
                published = normalize(item.findtext("pubDate", default=""))
                publisher = item.find("source")
                source_name = normalize(publisher.text if publisher is not None and publisher.text else "매체 미기재")
                description = item.findtext("description", default="")
                snippet = normalize(BeautifulText(description))
                if not link or not title:
                    continue
                text = f"{title}. {snippet}" if snippet else title
                results.append(Source(title=title, source=link, published=published or "미기재", kind=f"자동 수집 뉴스 · {source_name} · {topic}", text=text, period=period))
        except Exception as exc:
            errors.append(f"{topic} 뉴스 검색 실패: {exc}")
    return deduplicate(results), errors

def BeautifulText(value: str) -> str:
    # RSS 설명의 HTML 태그 및 엔티티를 정리한다.
    from html.parser import HTMLParser
    class TextOnly(HTMLParser):
        def __init__(self):
            super().__init__(); self.parts=[]
        def handle_data(self, data):
            self.parts.append(data)
    parser=TextOnly(); parser.feed(unescape(value)); return " ".join(parser.parts)
