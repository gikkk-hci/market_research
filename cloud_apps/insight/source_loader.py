from __future__ import annotations

from datetime import date
from io import BytesIO
import re

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader

from cloud_apps.insight.insight_core import Source, normalize


def read_pdf(uploaded_file) -> str:
    reader = PdfReader(BytesIO(uploaded_file.getvalue()))
    return normalize(" ".join(page.extract_text() or "" for page in reader.pages))


def read_url(url: str, timeout: int = 15) -> tuple[str, str]:
    response = requests.get(url, timeout=timeout, headers={"User-Agent": "MarketInsightPoC/1.0"})
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
        tag.decompose()
    title = soup.title.get_text(" ", strip=True) if soup.title else url
    body = normalize(soup.get_text(" ", strip=True))
    if not body:
        raise ValueError("페이지에서 본문 텍스트를 추출하지 못했습니다.")
    return title, body


def parse_article_lines(raw: str, period: str) -> list[Source]:
    """One article per line: title | published date | source | article text."""
    items = []
    for line_no, line in enumerate(raw.splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [part.strip() for part in line.split("|", 3)]
        if len(parts) != 4:
            raise ValueError(f"기사 데이터 {line_no}행은 제목 | 발행일 | 출처 | 본문 형식이어야 합니다.")
        title, published, source, text = parts
        items.append(Source(title=title, source=source, published=published or "미기재", kind="뉴스", text=text, period=period))
    return items


def make_source(title: str, source: str, published: str, kind: str, text: str, period: str) -> Source:
    return Source(title=title.strip() or "제목 미기재", source=source.strip() or "출처 미기재", published=published.strip() or "미기재", kind=kind, text=normalize(text), period=period)


def deduplicate(sources: list[Source]) -> list[Source]:
    seen = set()
    result = []
    for item in sources:
        key = re.sub(r"[^0-9a-z가-힣]", "", (item.title + item.text[:240]).lower())
        if key and key not in seen:
            seen.add(key)
            result.append(item)
    return result
