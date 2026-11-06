import pandas as pd
import plotly.express as px
import streamlit as st

from cloud_apps.fx.shared.countries import COUNTRIES, color_map


def apply_style():
    st.markdown("""<style>
    html,body,[class*="css"],[data-testid="stApp"]{font-family:'Noto Sans KR','Malgun Gothic',sans-serif;}
    [data-testid="stAppViewContainer"]{background:#f7f9fc;color:#17233b;}
    [data-testid="stSidebar"]{background:#eef3fa;border-right:1px solid #dce5f1;}
    div.block-container{max-width:1450px;padding-top:2.2rem;}
    .hero{padding:26px 30px;border-radius:20px;background:linear-gradient(115deg,#122a50,#264b8e);color:white;margin-bottom:1.2rem;}
    .hero h1{font-size:2rem;margin:0 0 .35rem 0;color:white;}.hero p{margin:0;color:#d8e7ff;}
    [data-testid="stMetric"]{background:white;border:1px solid #e2e9f2;border-radius:16px;padding:15px 18px;}
    [data-testid="stMetricLabel"]{color:#5c6d86;}[data-testid="stMetricValue"]{color:#173e77;}
    </style>""", unsafe_allow_html=True)


def hero(title, subtitle):
    st.markdown(f'<div class="hero"><h1>{title}</h1><p>{subtitle}</p></div>', unsafe_allow_html=True)


def style_chart(fig, height=360):
    fig.update_layout(template="plotly_white", height=height, margin=dict(l=15, r=15, t=35, b=20),
                      hovermode="x unified", legend_title_text="")
    return fig


def line_chart(frame, x, y, title="", color="#2d6cdf"):
    fig = px.line(frame, x=x, y=y, markers=True, title=title)
    fig.update_traces(line_color=color, line_width=2, marker_size=4, connectgaps=False)
    return style_chart(fig)


def rates_chart(rates, title=""):
    if rates.empty:
        st.info("선택 조건에 맞는 금리 자료가 없습니다.")
        return
    frame = rates.copy()
    frame["국가"] = frame.country.map(lambda c: COUNTRIES[c]["name"])
    frame["만기"] = frame.term.map(lambda t: "정책금리" if t == 0 else f"{int(t)}년물")
    # Reindex each series so missing months stay visible as gaps.
    groups = []
    for _, group in frame.groupby(["country", "term"]):
        full = pd.date_range(frame.month.min(), frame.month.max(), freq="MS")
        series = group.set_index("month").reindex(full).rename_axis("month").reset_index()
        series["국가"] = group["국가"].iloc[0]
        series["만기"] = group["만기"].iloc[0]
        groups.append(series)
    fig = px.line(pd.concat(groups), x="month", y="value", color="국가", line_dash="만기",
                  color_discrete_map=color_map(), markers=True, title=title,
                  labels={"month": "월", "value": "연 금리 (%)"})
    fig.update_traces(connectgaps=False, marker_size=4)
    st.plotly_chart(style_chart(fig), width="stretch")


def source_table(rates):
    if rates.empty:
        return
    rows = []
    for (country, term), group in rates.groupby(["country", "term"]):
        group = group.sort_values("month")
        last = group.iloc[-1]
        rows.append({"국가": COUNTRIES[country]["name"], "만기": "정책금리" if term == 0 else f"{int(term)}년",
                     "최근 금리 (%)": round(last.value, 4), "최근 기준월": last.month.strftime("%Y-%m"),
                     "최근 관측일/기준월": last.last_observed.strftime("%Y-%m-%d") if last.frequency == "일별" else last.month.strftime("%Y-%m"),
                     "조회된 첫 기준월": group.month.min().strftime("%Y-%m"), "관측월 수": len(group),
                     "최근월 원본 관측수": int(last.observations),
                     "원본 주기": last.frequency, "집계": last.aggregation, "출처": last.source})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.caption("표의 첫·마지막 기준월은 요청 기간 안의 실제 조회 범위입니다. 최신 월은 일부 날짜만 반영할 수 있으며, 평균에 포함되는 주말·휴일 관측 여부도 제공기관별로 다릅니다. 월별 원본의 기준일은 해당 기준월로 표시합니다.")
    with st.expander("원본 출처·지표 정의와 다운로드"):
        for (country, source), group in rates.groupby(["country", "source"]):
            last = group.iloc[-1]
            st.markdown(f"**{COUNTRIES[country]['name']} · [{source}]({last.source_url})**")
            st.write(last.definition)
        st.download_button("조회 금리 데이터 CSV 다운로드", rates.to_csv(index=False).encode("utf-8-sig"),
                           "금리_조회결과.csv", "text/csv")


def show_issues(issues):
    if issues:
        with st.expander(f"조회 상태와 미제공 자료 · {len(issues)}건", expanded=True):
            for issue in issues:
                st.warning(f"{issue['국가']}: {issue['내용']}")


def corr_text(value):
    if pd.isna(value):
        return "산출 불가"
    strength = "강한" if abs(value) >= .7 else "중간 정도의" if abs(value) >= .4 else "약한" if abs(value) >= .2 else "매우 약한"
    return f"{strength} {'양' if value >= 0 else '음'}의 선형 관계"
