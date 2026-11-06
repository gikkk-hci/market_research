import pandas as pd
import streamlit as st

from cloud_apps.fx.shared.countries import COUNTRIES
from cloud_apps.fx.shared.ui import hero, rates_chart, source_table, line_chart


def render(rates, first, second, terms, kind, start, end, displayed=None):
    hero("주요국 금리 비교", "9개 국가·지역의 공식 금리 · 같은 만기와 실제 관측월로 비교")
    st.caption(f"선택 기간: {start:%Y-%m-%d}~{end:%Y-%m-%d}. 기준금리와 국채는 정의·원본 주기·집계 방식을 구분합니다.")
    st.caption("같은 만기 국채라도 거래 수익률·파 수익률·추정 곡선 등 국가별 산출 방식이 다릅니다. 독일·프랑스 기준금리는 같은 ECB 시리즈를 사용합니다.")
    selected = rates[rates.term.isin(terms) & rates.country.isin(displayed or list(COUNTRIES))]
    rates_chart(selected, "주요국 기준금리 추이" if kind == "기준금리" else "국가별 동일 만기 국채 수익률")
    st.subheader("최신 금리와 실제 자료 범위")
    source_table(selected)
    name1, name2 = COUNTRIES[first]["name"], COUNTRIES[second]["name"]
    st.subheader(f"{name1} − {name2} 금리차")
    from cloud_apps.fx.shared.comparison import compare_rates
    for term in terms:
        pair = compare_rates(rates, first, second, term)
        if pair.empty:
            st.info(f"{'정책금리' if term == 0 else str(term)+'년물'}: 두 국가에 함께 있는 관측월이 없습니다.")
            continue
        label = "정책금리" if term == 0 else f"국채 {term}년물"
        full = pd.DataFrame({"month": pd.date_range(start.replace(day=1), end.replace(day=1), freq="MS")}).merge(pair, on="month", how="left")
        fig = line_chart(full, "month", "spread", label)
        fig.add_hline(y=0, line_dash="dot", line_color="#77869a")
        fig.update_yaxes(title="금리차 (%p)")
        fig.update_xaxes(title="월")
        st.plotly_chart(fig, width="stretch")
    st.caption(f"계산 방향: {name1} 금리 − {name2} 금리. 공통 관측월만 계산하며, 없는 만기를 다른 만기로 대체하지 않습니다.")
    if first in {"DE", "FR"} and second in {"DE", "FR"} and kind == "기준금리":
        st.info("독일과 프랑스는 같은 유로지역 정책금리를 사용하므로 기준금리차가 0입니다. 국채 수익률은 국가별로 다릅니다.")
