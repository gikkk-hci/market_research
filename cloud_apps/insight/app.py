from __future__ import annotations

from datetime import date
from pathlib import Path
import csv
import json

import streamlit as st

from cloud_apps.insight.indicator_api import fetch_catalog, shift_quarter
from cloud_apps.insight.insight_core import analyze, summarize, split_sentences
from cloud_apps.insight.risk_scoring import analyze_metric_series, score_agendas
from cloud_apps.insight.source_loader import deduplicate, make_source, parse_article_lines, read_pdf, read_url
from cloud_apps.insight.news_search import search_related_news
from cloud_apps.config import secret

ROOT = Path(__file__).resolve().parent
CATALOG_PATH = ROOT / "indicator_catalog.json"
DOMAIN_TERMS = {
    "주거 부동산": ("주거", "주택", "아파트", "부동산", "전세", "월세", "분양", "부동산PF"),
    "환율·금리": ("환율", "금리", "기준금리", "외환", "원화", "달러", "통화정책"),
    "NPL": ("NPL", "부실채권", "연체", "부도", "회수율", "대손", "충당금"),
    "기업금융": ("기업금융", "기업대출", "여신", "차주", "회사채", "조달", "기업부실"),
    "해외투자": ("해외투자", "해외법인", "국가위험", "외화", "환율", "투자손실"),
    "산업재 차량": ("산업재", "상용차", "건설기계", "트럭", "차량", "중고차", "담보가치"),
}

def source_evidence(domain: str, sources: list, limit: int = 3) -> list[tuple[object, str]]:
    terms = DOMAIN_TERMS.get(domain, ())
    matches = []
    for source in sources:
        for sentence in split_sentences(source.text):
            if any(term.lower() in sentence.lower() for term in terms):
                matches.append((source, sentence))
                if len(matches) >= limit:
                    return matches
    return matches

st.set_page_config(page_title="AI Market Insight & Capital Risk", page_icon="📊", layout="wide")
st.markdown("""<style>
  [data-testid="stAppViewContainer"] { background:#f3f6fb; color:#17263e; }
  [data-testid="stSidebar"] { background:#edf1f7; }
  button[kind="primary"] { background:#245bdb; border-color:#245bdb; }
</style>""", unsafe_allow_html=True)
st.title("AI Market Insight & Capital Risk Agenda")
st.caption("신용평가사 리포트·뉴스·외부 지표를 분기별로 결합해 캐피탈업 사업영역의 선제적 위험 요인과 스페셜 아젠다를 정리합니다.")

now = date.today()
with st.sidebar:
    st.header("분석 기준 분기")
    year_options = list(range(now.year, 2014, -1))
    c1, c2 = st.columns(2)
    with c1:
        selected_year = st.selectbox("연도", year_options, index=0)
    with c2:
        current_q = (now.month - 1) // 3 + 1
        selected_q = st.selectbox("분기", [1, 2, 3, 4], index=current_q - 1, format_func=lambda x: f"{x}분기")
    prev_year, prev_q = shift_quarter(selected_year, selected_q, -1)
    period = f"{selected_year}년 {selected_q}분기"
    period_code = f"{selected_year}Q{selected_q}"
    prior_period = f"{prev_year}년 {prev_q}분기"
    keywords = st.text_input("관심 산업·키워드", "부동산, NPL, 기업금융, 해외투자, 산업재 차량, 신용위험")
    with st.expander("외부 API 인증키", expanded=False):
        ecos_key = st.text_input("한국은행 ECOS API 키", type="password", key="ecos_api_key")
        rone_key = st.text_input("한국부동산원 R-ONE API 키", type="password", key="rone_api_key")
        kosis_key = st.text_input("KOSIS API 키", type="password", key="kosis_api_key")
        st.caption("입력하지 않으면 서버 Secrets의 ECOS_API_KEY, RONE_API_KEY, KOSIS_API_KEY를 사용합니다. 입력한 키는 현재 세션에서만 사용합니다.")

if "sources" not in st.session_state:
    st.session_state.sources = []
if "api_rows" not in st.session_state:
    st.session_state.api_rows = []
if "api_errors" not in st.session_state:
    st.session_state.api_errors = []
if "api_fetch_end" not in st.session_state:
    st.session_state.api_fetch_end = None
if "indicator_config_text" not in st.session_state:
    st.session_state.indicator_config_text = CATALOG_PATH.read_text(encoding="utf-8-sig") if CATALOG_PATH.exists() else '{"indicators": []}'

st.subheader("1. 리포트·뉴스 자료")
left, right = st.columns(2)
with left:
    pdfs = st.file_uploader("신용평가사 리포트 PDF", type=["pdf"], accept_multiple_files=True, key="risk_pdfs")
    urls_text = st.text_area("URL 자료 (한 줄에 하나씩)", height=95, key="risk_urls")
with right:
    st.caption("기사 형식: 제목 | 발행일 | 출처 또는 URL | 기사 본문")
    articles_text = st.text_area("경제·금융 뉴스 기사 데이터", height=115, key="risk_articles")
    prior_text = st.text_area(f"비교 참고 기사 데이터 · {prior_period} (선택)", height=75, key="risk_prior")
if st.button("리포트·뉴스 자료 추가", type="primary"):
    new_sources, errors = [], []
    for uploaded in pdfs or []:
        try:
            content = read_pdf(uploaded)
            new_sources.append(make_source(uploaded.name, uploaded.name, "미기재", "신용평가사 리포트", content, period))
        except Exception as exc:
            errors.append(f"{uploaded.name}: {exc}")
    for idx, raw_url in enumerate([x.strip() for x in urls_text.splitlines() if x.strip()], 1):
        try:
            title, content = read_url(raw_url)
            new_sources.append(make_source(title, raw_url, "미기재", "URL 자료", content, period))
        except Exception as exc:
            errors.append(f"URL {idx}: {exc}")
    try:
        new_sources.extend(parse_article_lines(articles_text, period))
    except ValueError as exc:
        errors.append(str(exc))
    st.session_state.sources = deduplicate(st.session_state.sources + deduplicate(new_sources))
    st.session_state.current_period = period
    try:
        st.session_state.previous_sources = parse_article_lines(prior_text, prior_period) if prior_text.strip() else []
        st.session_state.previous_for_period = period_code
    except ValueError as exc:
        errors.append(f"비교 자료: {exc}")
    st.session_state.source_errors = errors
if st.session_state.get("source_errors"):
    for error in st.session_state.source_errors:
        st.error(error)
pdf_sources = [s for s in st.session_state.sources if s.kind == "신용평가사 리포트" and s.period == period]
news_col, news_info = st.columns([1, 3])
with news_col:
    search_news = st.button("PDF 관련 뉴스 URL 자동 수집", disabled=not pdf_sources, help="현재 분기 PDF에서 확인되는 주제만 검색합니다.")
with news_info:
    st.caption("선택 분기 PDF에서 확인된 주제를 기준으로 뉴스 제목·발행일·매체·URL을 검색합니다. 검색된 결과는 자료와 아젠다 분석에 포함됩니다.")
if search_news:
    with st.spinner("PDF 주제와 선택 분기에 맞는 뉴스 검색 중…"):
        found_news, search_errors = search_related_news([s.text for s in pdf_sources], period)
    st.session_state.sources = deduplicate(st.session_state.sources + found_news)
    st.session_state.news_search_count = len(found_news)
    st.session_state.news_search_errors = search_errors
if st.session_state.get("news_search_count") is not None:
    st.info(f"최근 뉴스 검색 결과: {st.session_state.news_search_count}건 수집")
for error in st.session_state.get("news_search_errors", []):
    st.warning(error)

if st.session_state.sources:
    st.success(f"저장된 자료 {len(st.session_state.sources)}건 · 현재 선택 분기 {period}")
    with st.expander("입력 자료 목록", expanded=False):
        for source in st.session_state.sources:
            st.markdown(f"- **{source.title}** · {source.kind} · {source.published} · {source.period}")
            if source.source.startswith(("https://", "http://")):
                st.markdown(f"  - [뉴스/자료 URL 열기]({source.source})")
            else:
                st.caption(f"  출처: {source.source}")

comparison_sources = st.session_state.get("previous_sources", []) if st.session_state.get("previous_for_period") == period_code else []
source_analysis = analyze(st.session_state.sources, period, comparison_sources)

with st.expander("2. 외부 지표 API 연결 및 지표 코드 설정", expanded=True):
    st.markdown("API 키는 서버 Secrets 또는 왼쪽 메뉴에서 설정합니다. 지표별 통계표·항목·지역 코드는 각 기관의 통계코드 검색에서 확인해 아래 카탈로그에 입력하세요.")
    st.markdown("[R-ONE 통계코드 검색](https://www.reb.or.kr/r-one/portal/openapi/openApiGuideCdPage.do) · [R-ONE 개발가이드](https://www.reb.or.kr/r-one/portal/openapi/openApiDevPage.do) · [ECOS Open API](https://ecos.bok.or.kr/api/) · [KOSIS 공유서비스](https://kosis.kr/openapi/index/index.jsp)")
    catalog_text = st.text_area("indicator_catalog.json 설정", key="indicator_config_text", height=370)
    config_col1, config_col2 = st.columns([1, 3])
    with config_col1:
        save_config = st.button("지표 설정 적용")
    with config_col2:
        st.caption("API 키는 저장되지 않습니다. 통계표/항목 ID와 위험 방향을 설정한 지표만 조회됩니다.")
    try:
        catalog = json.loads(catalog_text)
        config_valid = isinstance(catalog, dict) and isinstance(catalog.get("indicators"), list)
        if not config_valid:
            st.error("카탈로그 JSON에 indicators 배열이 필요합니다.")
    except json.JSONDecodeError as exc:
        catalog, config_valid = {"indicators": []}, False
        st.error(f"카탈로그 JSON 오류: {exc}")
    if save_config and config_valid:
        st.success("현재 세션에 지표 설정을 적용했습니다. 다른 사용자의 설정은 바뀌지 않습니다.")
    if config_valid:
        st.download_button("지표 설정 JSON 다운로드", json.dumps(catalog, ensure_ascii=False, indent=2), file_name="indicator_catalog.json", mime="application/json")
    active = [item for item in catalog.get("indicators", []) if item.get("enabled")] if config_valid else []
    st.caption(f"활성 지표 {len(active)}개 · 지원 제공처: R-ONE, ECOS, KOSIS")
    if not active:
        st.info("기존 카탈로그는 코드가 비어 있는 예시이며 모든 지표가 비활성 상태입니다. 실제 통계 코드를 입력하고 enabled를 true로 설정해야 조회할 수 있습니다.")
    fetch_button = st.button("선택 분기 외부 지표 조회 및 분석", type="primary", disabled=not config_valid or not active)
    if fetch_button:
        start_year, start_q = shift_quarter(selected_year, selected_q, -19)
        start_period = f"{start_year}Q{start_q}"
        keys = {"ecos": ecos_key.strip() or secret("ECOS_API_KEY"),
                "r-one": rone_key.strip() or secret("RONE_API_KEY"),
                "kosis": kosis_key.strip() or secret("KOSIS_API_KEY")}
        with st.spinner(f"{start_period}부터 {period_code}까지 외부 통계를 조회합니다…"):
            rows, errors = fetch_catalog(catalog, keys, start_period, period_code)
        st.session_state.api_rows = rows
        st.session_state.api_errors = errors
        st.session_state.api_fetch_end = period_code
        st.session_state.api_fetch_start = start_period

if st.session_state.get("api_errors"):
    st.warning("일부 API 지표를 가져오지 못했습니다. 설정·인증·기관별 이용 권한을 확인하세요.")
    for error in st.session_state.api_errors:
        st.caption(f"{error.get('domain', '')} · {error.get('indicator', '')}: {error.get('error', '')}")

st.subheader("3. 분기 비교 및 이상 변동")
metric_results = analyze_metric_series(st.session_state.api_rows, period_code)
if st.session_state.api_fetch_end and st.session_state.api_fetch_end < period_code:
    st.warning(f"현재 선택 분기는 {period_code}이나 마지막 API 조회는 {st.session_state.api_fetch_end}까지입니다. 다시 조회하세요.")
if metric_results:
    metric_table = []
    for row in metric_results:
        metric_table.append({
            "사업영역": row["domain"], "지표": row["indicator"], "업종": row["industry"], "지역": row["region"], "현재 분기": row["quarter"],
            "현재값": row["value"], "전분기 변화율(%)": row["qoq_change_pct"], "전년 동기 변화율(%)": row["yoy_change_pct"],
            "이상 변동 백분위": row["anomaly_percentile"], "악화 지속 분기": row["adverse_quarters"], "시장 위험 신호(100)": round(row["signal_score"], 1) if row["signal_score"] is not None else "미산출", "근거 충족률(%)": round(row["signal_coverage"], 0), "출처": row["source"]
        })
    st.dataframe(metric_table, use_container_width=True, hide_index=True)
else:
    st.info("외부 API 지표가 아직 없습니다. 카탈로그에 통계 코드를 설정하고 조회하세요. 지표가 없을 때는 시장 리스크 점수를 산출하지 않습니다.")

st.markdown("**사업 포트폴리오 노출 자료 (최종 100점 점수용)**")
st.caption("사업영역별 실제 익스포저 금액(EAD 또는 사내에서 합의한 동일 기준)을 CSV로 넣으면 점수에 반영합니다. 모든 금액은 같은 통화·단위로 작성하고 사업영역 이름은 카탈로그와 동일하게 사용하세요. 파일은 앱 안에서만 처리합니다.")
exposure_file = st.file_uploader("포트폴리오 익스포저 CSV (선택)", type=["csv"], key="portfolio_exposure")
exposure_rows = []
if exposure_file is not None:
    try:
        csv_text = exposure_file.getvalue().decode("utf-8-sig")
        exposure_rows = list(csv.DictReader(csv_text.splitlines()))
        required = {"business_area", "quarter", "exposure_amount"}
        if not exposure_rows or not required.issubset(set(exposure_rows[0])):
            st.error("CSV 헤더에 business_area, quarter, exposure_amount가 있어야 합니다.")
            exposure_rows = []
        else:
            st.success(f"익스포저 {len(exposure_rows)}행 입력됨")
    except UnicodeDecodeError:
        st.error("CSV를 UTF-8로 저장한 뒤 업로드하세요.")

risk_agendas = score_agendas(metric_results, exposure_rows, period_code)
st.subheader("4. 캐피탈업 리스크 영향 점수 및 스페셜 아젠다")
st.markdown("**100점 초기 제안 가중치:** 전분기 악화 백분위 30 · 전년 동기 악화 백분위 25 · 과거 분포 대비 이상 변동 20 · 악화 지속성 10 · 포트폴리오 익스포저 15. 점수 산출 기준은 팀이 조정할 수 있으며, 통계 코드·비교 이력·위험 방향 또는 실제 익스포저가 빠지면 총점은 미산출로 표시합니다.")
st.caption("외부 지표는 시장 위험 신호입니다. 포트폴리오 CSV가 없으면 실제 캐피탈 자산 노출을 반영한 100점 종합점수라고 해석할 수 없습니다. 완성 점수는 입력된 사업영역 간 익스포저 최대값을 기준으로 상대화합니다.")

for agenda in risk_agendas:
    score_label = f"{agenda['risk_score']:.1f}/100" if agenda["risk_score"] is not None else f"미산출 · 근거 충족 {agenda['score_coverage']}/100"
    with st.container(border=True):
        st.markdown(f"### {agenda['rank']}순위 · {agenda['title']}　`{score_label}`")
        if agenda["signal_score"] is not None:
            signal_label = "완전 이력 기준" if agenda["signal_complete"] else "부분 이력 참고값 · 종합점수 미산출"
            st.write(f"시장 위험 신호 점수: {agenda['signal_score']:.1f}/100 ({signal_label}) · 비교 대상 업종: {', '.join(agenda['industries']) or '미분류'} · 지역: {', '.join(agenda['regions']) or '미분류'}")
        else:
            st.write("시장 위험 신호 점수: 산출할 수 있는 분기 API 지표가 없습니다.")
        if agenda["exposure_amount"] is not None:
            st.write(f"선택 분기 익스포저 금액: {agenda['exposure_amount']:,.2f} · 익스포저 배점: {agenda['exposure_points']:.1f}/15")
        else:
            st.write("익스포저: 자료 미입력 · 총점에서 미산출")
        text_evidence = source_evidence(agenda["domain"], source_analysis["sources"])
        if text_evidence:
            st.markdown("**신평사 리포트·뉴스 참고 근거 (점수 산정에는 미반영)**")
            for src, sentence in text_evidence:
                st.caption(f"{sentence} · {src.title} · {src.source} · {src.published}")
        if agenda["metrics"]:
            for metric in agenda["metrics"][:5]:
                qoq = "비교 불가" if metric["qoq_change_pct"] is None else f"전분기 {metric['qoq_change_pct']:+.2f}%"
                yoy = "비교 불가" if metric["yoy_change_pct"] is None else f"전년 동기 {metric['yoy_change_pct']:+.2f}%"
                anomaly = "이상 변동 비교 이력 부족" if metric["anomaly_percentile"] is None else f"이상 변동 백분위 {metric['anomaly_percentile']:.0f}"
                st.caption(f"{metric['indicator']} · {metric['industry']} · {metric['region']} · 시장 신호 {metric['signal_score']:.1f}/100 ({metric['signal_coverage']:.0f}% 이력 충족) · {qoq} · {yoy} · {anomaly} · {metric['source']}")
        else:
            st.caption("활성화된 지표 API를 연결하면 지역·업종별 근거 지표가 표시됩니다.")

st.subheader("5. 자료 요약 및 시장 이슈")
if source_analysis["sources"]:
    for source in source_analysis["sources"]:
        with st.expander(source.title):
            st.write(f"출처: {source.source} · 발행일: {source.published} · 유형: {source.kind}")
            st.write(summarize(source.text))
else:
    st.info("현재 분기에 배정한 신용평가사 리포트·뉴스 자료가 없습니다.")
issue_rows = []
for row in source_analysis["topics"]:
    if row["count"] or row["previous_count"]:
        issue_rows.append({"자료 주제": row["topic"], "현재 언급 문장 수": row["count"], "전기 대비 문장 수": row["delta"] if row["delta"] is not None else "비교 자료 없음"})
if issue_rows:
    st.dataframe(issue_rows, use_container_width=True, hide_index=True)

st.subheader("6. C-Level 메일 보고 초안")
subject = f"[마켓 리스크 인사이트] {period} 스페셜 아젠다 및 핵심 위험요인"
mail_lines = ["안녕하세요.", "", f"{period} 신용평가사 리포트·뉴스 및 외부 통계 분석 결과를 공유드립니다.", "", "스페셜 아젠다 리스트 (캐피탈업 리스크 우선순위)"]
for agenda in risk_agendas:
    score = f"{agenda['risk_score']:.1f}/100" if agenda["risk_score"] is not None else "점수 미산출 (근거 부족)"
    mail_lines.append(f"{agenda['rank']}순위. {agenda['title']} — {score}")
    if agenda["metrics"]:
        m = agenda["metrics"][0]
        qoq = "전분기 비교 불가" if m["qoq_change_pct"] is None else f"전분기 {m['qoq_change_pct']:+.2f}%"
        yoy = "전년 동기 비교 불가" if m["yoy_change_pct"] is None else f"전년 동기 {m['yoy_change_pct']:+.2f}%"
        mail_lines.append(f"   근거 지표: {m['indicator']} · {m['region']} · {qoq} · {yoy} · 출처: {m['source']}")
    else:
        mail_lines.append("   근거: 해당 사업영역 지표 API가 연결되지 않았거나 선택 분기 자료가 없습니다.")
    text_evidence = source_evidence(agenda["domain"], source_analysis["sources"], limit=2)
    if text_evidence:
        mail_lines.append("   신평사 리포트·뉴스 참고 근거 (점수 미반영):")
        for src, sentence in text_evidence:
            mail_lines.append(f"   - {sentence} (출처: {src.title}, {src.source}, {src.published})")
    if agenda["exposure_amount"] is None:
        mail_lines.append("   익스포저 반영: 미입력 — 최종 100점 점수 확정을 위해 사업 포트폴리오 자료가 필요합니다.")
mail_lines += ["", "자료 해석 및 검토 포인트", "- 외부 지표의 전분기·전년 동기 변화, 이상 변동, 업종·지역별 위험 신호를 확인했습니다.", "- 자료가 연결되지 않았거나 비교 이력이 부족한 항목은 점수를 임의로 채우지 않고 미산출로 표시했습니다.", "- 아젠다와 위험 점수는 입력된 통계 코드·위험 방향 및 포트폴리오 익스포저 설정에 따른 분석 결과입니다.", "", "배포 전 통계 출처와 사내 익스포저 기준을 확인해 주세요.", "", "감사합니다."]
body = "\n".join(mail_lines)
if st.session_state.get("_risk_mail_source") != (subject, body):
    st.session_state.risk_email_subject = subject
    st.session_state.risk_email_body = body
    st.session_state._risk_mail_source = (subject, body)
email_subject = st.text_input("메일 제목", key="risk_email_subject")
email_body = st.text_area("메일 본문", height=480, key="risk_email_body")
report_lines = [f"# {period} 캐피탈업 시장 리스크 분석", "", "## 스페셜 아젠다 리스트"]
for agenda in risk_agendas:
    score = f"{agenda['risk_score']:.1f}/100" if agenda["risk_score"] is not None else f"미산출 · 근거 충족 {agenda['score_coverage']}/100"
    report_lines += [f"### {agenda['rank']}순위. {agenda['title']} ({score})"]
    for metric in agenda["metrics"][:5]:
        report_lines.append(f"- {metric['indicator']} · {metric['region']} · 현재 {metric['value']} · QoQ {metric['qoq_change_pct']} · YoY {metric['yoy_change_pct']} · 이상 변동 백분위 {metric['anomaly_percentile']} · {metric['source']}")
    if not agenda["metrics"]: report_lines.append("- 지표 API 미연결 또는 해당 분기 자료 없음")
    for src, sentence in source_evidence(agenda["domain"], source_analysis["sources"], limit=3):
        report_lines.append(f"- 신평사 리포트·뉴스 참고 근거 (점수 미반영): {sentence} (출처: {src.title}, {src.source}, {src.published})")
    if agenda["exposure_amount"] is None: report_lines.append("- 포트폴리오 익스포저 미입력: 종합점수 산출 불가")
report_lines += ["", "## 분석 기준", "- QoQ 악화 백분위 30점, YoY 악화 백분위 25점, 이상 변동 20점, 악화 지속성 10점, 상대 익스포저 15점", "- 제안 가중치이며, 불충분한 근거는 미산출로 유지"]
report = "\n".join(report_lines)
col_a, col_b = st.columns(2)
with col_a:
    st.download_button("메일 초안 다운로드", f"제목: {email_subject}\n\n{email_body}", file_name="quarterly_market_risk_email.txt", mime="text/plain")
with col_b:
    st.download_button("스페셜 아젠다 보고서 다운로드", report, file_name="quarterly_risk_agendas.md", mime="text/markdown")

with st.expander("점수 산정·해석 기준"):
    st.markdown("""
- **전분기·전년 동기 악화 백분위:** 각 지표의 위험 방향을 지정한 뒤, 과거 같은 시계열의 변화율 분포에서 현재 변동이 얼마나 악화 쪽에 위치하는지 계산합니다. 전분기 30점, 전년 동기 25점입니다.
- **이상 변동:** 최근 최대 12개 분기 중앙값과 MAD(중앙절대편차)를 사용해 급격한 수준 변화를 과거 분포와 비교합니다. 20점입니다.
- **악화 지속성:** 악화 흐름이 연속된 분기 수를 최대 4분기까지 반영합니다. 10점입니다.
- **사업 포트폴리오 익스포저:** 동일 기준으로 입력된 사업영역별 EAD 합계 중 가장 큰 영역 대비 상대 비중을 15점에 반영합니다. 내부 익스포저 자료가 없으면 종합점수는 완성되지 않습니다.
- 지표 데이터는 공식 API에서 가져오며, 지표 단위·분기 집계 방식(last/mean/sum)·위험 방향은 지표별로 설정합니다. 설정되지 않은 방향이나 충분한 비교 이력이 없는 지표는 점수 구성에서 미산출 처리합니다.
- API 지표는 시장 신호를 보여줍니다. 실제 예상손실(EAD×PD×LGD)이나 사내 신용정책 판단을 대체하지 않습니다.
""")
