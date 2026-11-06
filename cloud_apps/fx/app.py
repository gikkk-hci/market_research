"""Streamlit entry point. Each page lives in its own dashboard_pages subfolder."""
from datetime import date
import hashlib

import streamlit as st

from cloud_apps.fx.dashboard_pages.relationship.page import render as render_relationship
from cloud_apps.fx.dashboard_pages.global_rates.page import render as render_global
from cloud_apps.fx.shared.countries import COUNTRIES, country_name, supported_terms
from cloud_apps.fx.shared.credentials import load_data_key
from cloud_apps.fx.shared.service import load_rates, load_fx
from cloud_apps.fx.shared.ui import apply_style, hero, show_issues

st.set_page_config(page_title="환율 × 주요국 금리", page_icon="📈", layout="wide")
apply_style()

with st.sidebar:
    page = st.radio("페이지", ["환율·금리차 분석", "주요국 금리 비교"], key="navigation")
    st.header("조회 설정")
    first = st.selectbox("첫 번째 국가", list(COUNTRIES), index=0, format_func=country_name)
    second = st.selectbox("두 번째 국가", list(COUNTRIES), index=1, format_func=country_name)
    if page == "주요국 금리 비교":
        displayed = st.multiselect("그래프에 표시할 국가", list(COUNTRIES), default=list(COUNTRIES), format_func=country_name)
    else:
        displayed = [first, second]
    start = st.date_input("시작일", value=date(2019, 1, 1), min_value=date(1945, 1, 1), max_value=date.today())
    end = st.date_input("종료일", value=date.today(), min_value=date(1945, 1, 1), max_value=date.today())
    kind = st.radio("금리 유형", ["국채 수익률", "기준금리"], horizontal=True)
    countries = list(dict.fromkeys([first, second, *displayed]))
    policy_mode = "월평균 (일별 집계)"
    korea_source = "KTS 거래수익률 (기존)"
    if kind == "기준금리":
        policy_mode = st.selectbox("정책금리 집계", ["월평균 (일별 집계)", "월말값 (기존)"])
        terms, corr_term = [0], 0
    else:
        if "KR" in countries:
            korea_source = st.selectbox("한국 국채 자료", ["KTS 거래수익률 (기존)", "OECD 10년물 (FRED 공개 CSV)"])
        term_choices = sorted({term for c in countries for term in supported_terms(c, korea_source)})
        terms = st.multiselect("동일 만기 선택", term_choices, default=[t for t in (3, 10) if t in term_choices],
                              format_func=lambda t: f"{t}년물")
        options = terms or term_choices or [10]
        common = set(supported_terms(first, korea_source)) & set(supported_terms(second, korea_source))
        preferred = next((t for t in (3, 10, *options) if t in options and t in common), options[0])
        corr_term = st.selectbox("상관분석 만기", options, index=options.index(preferred), format_func=lambda t: f"{t}년물")
        st.caption("없는 만기는 다른 만기로 대체하지 않습니다. 한국 KTS 1년물 등은 해당 기간에 자료가 없을 수 있습니다.")
    currency1, currency2 = COUNTRIES[first]["currency"], COUNTRIES[second]["currency"]
    directions = [(currency2, currency1)] if currency1 == currency2 else [(currency2, currency1), (currency1, currency2)]
    base, quote = st.selectbox("환율 표시 방향", directions, format_func=lambda p: f"{p[0]}/{p[1]}")
    with st.expander("인증키 설정"):
        entered = st.text_input("공공데이터포털 인증키", type="password", help="비워두면 환경변수 또는 공통 .env의 키를 사용합니다. 기존 secrets.toml도 보조 설정으로 지원합니다.")
        st.caption("비워두면 서버의 DATA_GO_KR_KEY 설정을 사용합니다. 금융위원회와 IBK 조회에 사용하며 해외 공식 자료는 별도 키 없이 조회합니다.")
    run = st.button("데이터 조회", type="primary", width="stretch")
    st.caption("국가별 제공기관 API와 공식 공개 CSV만 사용합니다. 공개 파일은 API와 구분해 표시합니다.")

if first == second:
    st.warning("서로 다른 두 국가를 선택해 주세요.")
    st.stop()
if start > end:
    st.warning("시작일은 종료일보다 빠르거나 같아야 합니다.")
    st.stop()
if not terms:
    st.info("조회할 만기를 하나 이상 선택해 주세요.")
    st.stop()
key = entered.strip() or load_data_key()
needs_fx = page == "환율·금리차 분석"
signature = (tuple(countries), start, end, kind, policy_mode, korea_source, base, quote, needs_fx,
             hashlib.sha256(key.encode()).hexdigest())

if run:
    with st.spinner("공식 금리 자료를 조회하고 월별로 정리합니다…"):
        rates, issues = load_rates(countries, kind, start, end, key, policy_mode, korea_source)
    import pandas as pd
    fx, fx_issue = pd.DataFrame(columns=["month", "fx"]), ""
    if needs_fx:
        with st.spinner("IBK 월평균 환율 조회 중입니다. 처음 조회하는 긴 기간은 몇 분 걸릴 수 있습니다…"):
            fx, fx_issue = load_fx(key, start, end, base, quote)
    st.session_state["dataset_v2"] = {"signature": signature, "rates": rates, "issues": issues,
                                       "fx": fx, "fx_issue": fx_issue}

loaded = st.session_state.get("dataset_v2")
if loaded is None or loaded["signature"] != signature:
    hero("환율 × 주요국 금리", "공식 데이터로 국가별 금리와 환율의 관계를 살펴보세요")
    st.info("설정을 선택한 후 ‘데이터 조회’를 누르세요. 설정이 바뀌면 다시 조회해야 합니다. 캐시된 자료는 재사용합니다.")
    st.stop()

issues = list(loaded["issues"])
if kind == "국채 수익률":
    for country in countries:
        available = set(loaded["rates"].loc[loaded["rates"].country == country, "term"])
        missing = [term for term in terms if term not in available]
        if missing and available:
            issues.append({"국가": country_name(country),
                           "내용": "선택한 " + ", ".join(f"{term}년물" for term in missing) + " 자료가 연결된 출처 또는 선택 기간에 없습니다. 있는 만기의 자료만 표시합니다."})
show_issues(issues)
if page == "주요국 금리 비교":
    render_global(loaded["rates"], first, second, terms, kind, start, end, displayed)
else:
    render_relationship(loaded["rates"], loaded["fx"], first, second, base, quote, terms,
                         corr_term, kind, start, end, loaded["fx_issue"])
