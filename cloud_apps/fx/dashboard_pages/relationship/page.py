from datetime import date

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

from cloud_apps.fx.shared.analysis import coverage_table, consecutive_month_changes, rolling_level_correlation
from cloud_apps.fx.shared.comparison import compare_rates
from cloud_apps.fx.shared.countries import COUNTRIES
from cloud_apps.fx.shared.news import headlines
from cloud_apps.fx.shared.ui import hero, line_chart, rates_chart, source_table, style_chart, corr_text
from cloud_apps.fx.dashboard_pages.relationship.hedge_reference import render as hedge_reference


def render(rates, fx, first, second, base, quote, terms, corr_term, kind, start, end, fx_issue=""):
    fx = fx.copy()
    fx["month"] = pd.to_datetime(fx["month"])
    name1, name2 = COUNTRIES[first]["name"], COUNTRIES[second]["name"]
    rate_label = "기준금리" if kind == "기준금리" else f"국채 {corr_term}년물"
    hero("환율 × 금리차", f"{name1} − {name2} 금리차와 {base}/{quote} 환율의 관계")
    st.caption(f"선택 기간: {start:%Y-%m-%d}~{end:%Y-%m-%d} · 금리차 = {name1} 금리 − {name2} 금리")
    st.caption("같은 만기라도 국가별 국채의 거래 종가·파 수익률·추정 금리곡선 등 산출 방식이 다릅니다. 정책금리는 국가별 지표와 제도 변경을 원본 정의에서 확인하세요.")
    if fx_issue:
        st.warning(fx_issue)
    if end >= date.today().replace(day=1):
        st.caption("월평균 환율은 완료된 월까지만 조회합니다. 현재 월의 금리는 있을 수 있지만 환율 상관분석에는 포함하지 않습니다.")
    comparison = compare_rates(rates, first, second, corr_term)
    joined = fx.merge(comparison, on="month", how="inner").sort_values("month")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric(f"{base}/{quote} 최근 월평균", f"{fx.iloc[-1].fx:,.2f}" if not fx.empty else "자료 없음")
    c2.metric(f"{name1} {rate_label}", f"{comparison.iloc[-1]['first']:.3f}%" if not comparison.empty else "공통 자료 없음")
    c3.metric(f"{name2} {rate_label}", f"{comparison.iloc[-1]['second']:.3f}%" if not comparison.empty else "공통 자료 없음")
    c4.metric(f"{name1} − {name2}", f"{comparison.iloc[-1].spread:+.3f}%p" if not comparison.empty else "자료 없음")
    if not comparison.empty:
        st.caption(f"양국 금리 지표의 최근 공통 기준월: {comparison.iloc[-1].month:%Y-%m}")

    a = rates[(rates.country == first) & (rates.term == corr_term)]
    b = rates[(rates.country == second) & (rates.term == corr_term)]
    labels = (f"{name1} 금리", f"{name2} 금리")
    audit = coverage_table(start, end, fx, a.month, b.month, labels=labels)
    missing = audit[~audit["공통 관측"]]
    with st.expander(f"공통 관측에서 빠진 달 · {len(missing)}개월 / 선택 {len(audit)}개월"):
        if missing.empty:
            st.write("선택 기간의 모든 달에 환율과 양국 금리 자료가 있습니다.")
        else:
            display = missing.drop(columns="공통 관측").copy()
            display["month"] = display.month.dt.strftime("%Y-%m")
            for column in ("환율", *labels):
                display[column] = display[column].map({True: "있음", False: "없음"})
            st.dataframe(display.rename(columns={"month": "월"}), hide_index=True, width="stretch")
            st.caption("선택 금리 유형·상관분석 만기 기준입니다. '없음'은 해당 조회 결과에 유효한 값이 없다는 뜻이며, 값을 보간하지 않습니다.")

    left, right = st.columns(2)
    with left:
        if fx.empty:
            st.info("이 통화쌍의 환율 자료가 없어 환율 그래프와 상관분석을 표시하지 않습니다.")
        else:
            full_fx = audit[["month"]].merge(fx, on="month", how="left")
            figure = line_chart(full_fx, "month", "fx", f"{base}/{quote} 월평균 환율")
            figure.update_yaxes(title=f"{quote} / {base} (API 고시 단위)")
            figure.update_xaxes(title="월")
            st.plotly_chart(figure, width="stretch")
    with right:
        rates_chart(rates[rates.country.isin([first, second]) & rates.term.isin(terms)], "양국 동일 지표 금리 비교")

    st.subheader(f"환율과 {name1} − {name2} 금리차의 월별 흐름")
    if not comparison.empty:
        timeline = audit[["month"]].merge(fx, on="month", how="left").merge(comparison, on="month", how="left")
        flow = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=.1)
        flow.add_trace(go.Scatter(x=timeline.month, y=timeline.fx, name=f"{base}/{quote}",
                                 mode="lines+markers", connectgaps=False, line=dict(color="#2d6cdf")), row=1, col=1)
        flow.add_trace(go.Scatter(x=timeline.month, y=timeline.spread, name=f"{name1} − {name2}",
                                 mode="lines+markers", connectgaps=False, line=dict(color="#c4334b")), row=2, col=1)
        flow.add_hline(y=0, row=2, col=1, line_dash="dot", line_color="#77869a")
        flow.update_yaxes(title_text=f"{base}/{quote}", row=1, col=1)
        flow.update_yaxes(title_text="금리차 (%p)", row=2, col=1)
        st.plotly_chart(style_chart(flow, 520), width="stretch")
        st.caption(f"금리차 = {name1} {rate_label} − {name2} {rate_label}. 자료가 없는 달은 선이 끊깁니다.")
    else:
        st.info("선택 만기의 공통 금리 자료가 없어 금리차를 계산할 수 없습니다.")

    st.subheader("환율과 금리차의 상관관계")
    rolling = pd.DataFrame()
    if len(joined) < 6:
        st.info(f"환율과 양국 금리가 함께 있는 달은 {len(joined)}개입니다. 6개월 이상일 때 상관분석을 표시합니다.")
    else:
        level = joined.fx.corr(joined.spread)
        change = consecutive_month_changes(joined)
        change_corr = change.fx_change.corr(change.spread_change) if len(change) >= 5 else float("nan")
        scatter_data = joined.assign(연도=joined.month.dt.year.astype(str))
        left, right = st.columns([2, 1])
        with left:
            scatter = px.scatter(scatter_data, x="spread", y="fx", color="연도", hover_data={"month": "|%Y-%m"},
                                 labels={"spread": f"{name1} − {name2} {rate_label} 차이 (%p)", "fx": f"{base}/{quote} 월평균"})
            scatter.update_traces(marker=dict(size=9, opacity=.8))
            st.plotly_chart(style_chart(scatter), width="stretch")
        with right:
            st.metric("공통 관측월", f"{len(joined)}개월")
            st.metric("금리차와 환율 수준 상관", f"{level:+.2f}" if pd.notna(level) else "산출 불가")
            st.metric("월별 변화 상관", f"{change_corr:+.2f}" if pd.notna(change_corr) else "산출 불가")
            st.caption(f"실제 공통 기간: {joined.month.min():%Y-%m}~{joined.month.max():%Y-%m}")
            st.caption(f"월별 변화는 연속된 두 달 {len(change)}쌍만 사용합니다.")
        st.write(f"수준 상관은 **{corr_text(level)}**, 같은 달의 변화 상관은 **{corr_text(change_corr)}**입니다.")
        st.caption("수준 상관은 같은 달 두 값의 높낮이를, 변화 상관은 환율 증감률(%)과 금리차 변화(%p)를 비교합니다. 강도 구분은 설명용 기준입니다. 추세·시기 차이가 영향을 줄 수 있으며, 인과관계·금리 기여도·통계적 유의성을 검증한 결과는 아닙니다.")
        rows = []
        periods = joined.assign(period=(joined.month.dt.year // 2) * 2)
        for _, group in periods.groupby("period"):
            if len(group) >= 6:
                rows.append({"실제 관측 기간": f"{group.month.min():%Y-%m}~{group.month.max():%Y-%m}",
                             "공통 관측월": len(group), "수준 상관": group.fx.corr(group.spread)})
        st.markdown("**2년 단위 수준 상관**")
        st.dataframe(pd.DataFrame(rows).style.format({"수준 상관": "{:+.2f}"}), hide_index=True, width="stretch")
        st.caption("달력 기준 2년 구간에서 관측월이 6개 이상인 구간만 표시합니다. 마지막 구간은 아직 2년이 되지 않았을 수 있습니다.")
        rolling = rolling_level_correlation(joined, start, end)
        if not rolling.empty:
            st.markdown("**최근 24개월 이동 수준 상관**")
            full_rolling = audit[["month"]].merge(rolling, on="month", how="left")
            graph = line_chart(full_rolling, "month", "correlation")
            graph.update_yaxes(title="상관계수", range=[-1.05, 1.05])
            graph.update_xaxes(title="월")
            graph.add_hline(y=0, line_dash="dot", line_color="#77869a")
            st.plotly_chart(graph, width="stretch")
            st.caption("각 시점까지 최근 24개월 중 공통 관측이 18개월 이상일 때 계산합니다. 중첩되는 구간의 값은 서로 독립적이지 않습니다.")

    st.subheader("기간 요약과 데이터 정의")
    if len(fx) > 1:
        first_fx, last_fx = fx.iloc[0], fx.iloc[-1]
        st.write(f"{first_fx.month:%Y-%m}~{last_fx.month:%Y-%m} {base}/{quote} 월평균 환율은 "
                 f"{first_fx.fx:,.2f}에서 {last_fx.fx:,.2f}로 {100 * (last_fx.fx / first_fx.fx - 1):+.1f}% 변했습니다.")
    st.caption("환율은 IBK 월평균입니다. 일부 날짜만 선택한 달은 금리가 해당 날짜 범위의 평균일 수 있습니다. JPY 등 통화의 고시 단위와 원본 산출 방식이 다를 수 있습니다. 출처·집계 방식·최근 관측일을 아래 표에서 확인하세요.")
    source_table(rates[rates.country.isin([first, second]) & rates.term.isin(terms)])
    with st.expander("관련 최근 뉴스 · 해석 참고"):
        articles = headlines(f"{name1} {name2} {base} {quote} 환율 금리")
        for article in articles:
            st.markdown(f"- [{article['title']}]({article['url']}) · {article['date']}")
        if not articles:
            st.info("뉴스를 가져오지 못했습니다. 금리·환율 분석은 정상 조회된 공식 자료로 계속 표시합니다.")
        st.caption("뉴스는 최근 변동 배경을 살펴보는 참고 자료이며 수치 데이터에 사용하지 않습니다. 제목만으로 선택 기간의 원인이나 금리의 기여도를 확정하지 않습니다.")
    hedge_reference(rolling)
