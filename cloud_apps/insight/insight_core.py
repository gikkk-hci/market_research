from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from datetime import date
from typing import Iterable


@dataclass
class Source:
    title: str
    source: str
    published: str
    kind: str
    text: str
    period: str = "분석 기간"


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def split_sentences(text: str) -> list[str]:
    text = normalize(text)
    if not text:
        return []
    parts = re.split(r"(?<=[.!?。])\s+|(?<=다\.)\s+|\n+", text)
    return [p.strip(" -•\t") for p in parts if len(p.strip()) >= 12]


def summarize(text: str, limit: int = 3) -> str:
    """Return extractive sentences; no facts are generated beyond the source text."""
    sentences = split_sentences(text)
    if len(sentences) <= limit:
        return " ".join(sentences) if sentences else normalize(text)[:500]
    weights = ("주요", "증가", "감소", "전망", "변화", "위험", "금리", "환율", "부동산", "신용", "시장", "영향", "상승", "하락")
    ranked = sorted(enumerate(sentences), key=lambda pair: (sum(pair[1].count(w) for w in weights), -pair[0]), reverse=True)
    chosen = sorted(index for index, _ in ranked[:limit])
    return " ".join(sentences[i] for i in chosen)


TOPICS: dict[str, tuple[str, ...]] = {
    "주거 부동산": ("주거", "주택", "아파트", "부동산", "전세", "월세", "분양", "매매", "주택시장"),
    "환율·금리": ("환율", "금리", "기준금리", "국채금리", "달러", "원화", "외환", "통화정책"),
    "신용위험": ("신용위험", "연체율", "부실", "신용등급", "대손", "충당금", "채무불이행"),
    "금융시장": ("금융시장", "채권", "주식시장", "유동성", "자금조달", "스프레드", "시장변동성"),
    "카드·캐피탈": ("카드업", "카드사", "캐피탈", "할부금융", "여전", "리스금융"),
}


def matched_topics(text: str) -> list[str]:
    lower = text.lower()
    return [topic for topic, terms in TOPICS.items() if any(term.lower() in lower for term in terms)]


def topic_evidence(sources: Iterable[Source], topic: str) -> list[tuple[Source, str]]:
    terms = TOPICS[topic]
    matches: list[tuple[Source, str]] = []
    for source in sources:
        for sentence in split_sentences(source.text):
            if any(term.lower() in sentence.lower() for term in terms):
                matches.append((source, sentence))
    return matches


def analyze(sources: list[Source], current_period: str, previous_sources: list[Source] | None = None) -> dict:
    previous_sources = previous_sources or []
    current_sources = [s for s in sources if s.period == current_period]
    topic_rows = []
    for topic in TOPICS:
        evidence = topic_evidence(current_sources, topic)
        previous_count = len(topic_evidence(previous_sources, topic))
        current_count = len(evidence)
        delta = current_count - previous_count if previous_sources else None
        topic_rows.append({"topic": topic, "count": current_count, "previous_count": previous_count, "delta": delta, "evidence": evidence})
    return {"sources": current_sources, "topics": topic_rows, "source_count": len(current_sources)}


def recommend_agendas(analysis: dict) -> list[dict]:
    by_topic = {row["topic"]: row for row in analysis["topics"]}
    definitions = [
        ("지역별 주거 부동산 시장 동향 분석", "주거 부동산", "지역별 주거 부동산 동향이 금융업에 미치는 영향 및 시사점"),
        ("환율·금리 등 주요 금융지표 분석", "환율·금리", "환율·금리 변화가 금융업에 미치는 영향 및 시사점"),
    ]
    agendas = []
    used = {"주거 부동산", "환율·금리"}
    for rank, (title, topic, question) in enumerate(definitions, start=1):
        row = by_topic[topic]
        agendas.append({"rank": rank, "title": title, "topic": topic, "question": question, "evidence": row["evidence"], "count": row["count"], "reason": "사용자가 지정한 우선 검토 예시"})
    extras = sorted((r for r in analysis["topics"] if r["topic"] not in used and r["count"] > 0), key=lambda r: (-r["count"], r["topic"]))
    for row in extras:
        if len(agendas) >= 5:
            break
        agendas.append({"rank": len(agendas) + 1, "title": f"{row['topic']} 동향 분석", "topic": row["topic"], "question": f"{row['topic']} 이슈의 금융업 영향과 경영진 검토 포인트", "evidence": row["evidence"], "count": row["count"], "reason": f"입력 자료에서 관련 내용 {row['count']}건 확인"})
    return agendas


def build_email(analysis: dict, agendas: list[dict], period: str) -> tuple[str, str]:
    today = date.today().isoformat()
    subject = f"[마켓 인사이트] {period} 주요 이슈 및 우선 검토 아젠다"
    lines = [f"안녕하세요.", "", f"{period} 분석 자료를 바탕으로 확인한 주요 시장 이슈와 우선 검토 아젠다를 공유드립니다.", "", f"분석 자료: {analysis['source_count']}건"]
    if not analysis["source_count"]:
        lines += ["", "※ 해당 기간에 분석 대상으로 등록된 자료가 없습니다. 자료를 추가한 뒤 결과를 확인해 주세요."]
    lines += ["", "주요 이슈"]
    found = [r for r in analysis["topics"] if r["count"]]
    if found:
        for row in sorted(found, key=lambda r: (-r["count"], r["topic"])):
            delta = "전기 비교 자료 미제공" if row["delta"] is None else f"전기 대비 {row['delta']:+d}건"
            lines.append(f"- {row['topic']}: 관련 언급 {row['count']}건 ({delta})")
    else:
        lines.append("- 제공된 자료에서 사전 정의된 이슈 키워드가 확인되지 않았습니다.")
    lines += ["", "우선 검토 아젠다"]
    for agenda in agendas:
        lines.append(f"{agenda['rank']}순위. {agenda['title']} — {agenda['reason']}")
        if agenda["evidence"]:
            source, sentence = agenda["evidence"][0]
            lines.append(f"   근거: {sentence} (출처: {source.title}, {source.source})")
        else:
            lines.append("   근거: 입력 자료에서 관련 내용을 찾지 못해 분석이 필요합니다.")
        lines.append(f"   검토 포인트: {agenda['question']}")
    lines += ["", "본 초안은 입력 자료의 요약이며, 배포 전 내용과 출처를 확인해 주세요.", "", "감사합니다."]
    return subject, "\n".join(lines)
