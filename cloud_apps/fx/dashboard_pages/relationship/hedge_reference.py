import pandas as pd
import streamlit as st


def render(rolling):
    st.subheader("환헤지 전략 참고")
    if not rolling.empty:
        latest = rolling.iloc[-1]
        st.write(f"최근 24개월 이동 수준 상관은 {latest.month:%Y-%m} 기준 {latest.correlation:+.2f}입니다. "
                 "부호의 변화는 과거 관계가 일정하지 않았다는 관찰이며, 다음 환율 방향이나 유리한 헤지 비율을 뜻하지 않습니다.")
    st.write("외화를 받을 예정이거나 보유 중이면 해당 외화의 약세가 수취액을 줄이고, 외화를 지급할 예정이면 해당 외화의 강세가 지급 부담을 늘립니다. "
             "수취·지급 시점과 확정 금액을 먼저 정한 뒤, 감당할 수 있는 환율 변동 폭에 맞춰 일부 또는 전부를 고정하는 방안을 비교할 수 있습니다.")
    st.caption("실제 선택에는 같은 만기의 선도환율 견적·호가 차이·수수료·계약 조건이 필요합니다. 국채 금리차와 상관계수만으로 최적 헤지 비율이나 헤지 수익을 계산하지 않습니다.")
    st.markdown("[BIS 외환 헤지 비용 설명](https://www.bis.org/publications/qr-202512/global-fx-markets-when-hedging-takes-centre-stage)")
