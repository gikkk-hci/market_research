COUNTRIES = {
    "KR": {"name": "한국", "currency": "KRW", "policy": "KR", "color": "#2d6cdf", "definition": "한국은행 기준금리"},
    "US": {"name": "미국", "currency": "USD", "policy": "US", "color": "#c4334b", "definition": "연방기금금리 목표 범위 중간값"},
    "CN": {"name": "중국", "currency": "CNY", "policy": "CN", "color": "#e29625", "definition": "2019-08-20부터 1년 LPR, 이전에는 1년 공식 대출금리. 7일 역레포 금리와 다름"},
    "JP": {"name": "일본", "currency": "JPY", "policy": "JP", "color": "#8c64bd", "definition": "BIS 선정 단기 정책금리. 기간별 운영목표 변경은 원문 정의 참조"},
    "GB": {"name": "영국", "currency": "GBP", "policy": "GB", "color": "#239185", "definition": "영란은행 공식 Bank Rate"},
    "DE": {"name": "독일", "currency": "EUR", "policy": "XM", "color": "#596579", "definition": "유로지역 ECB: 2024-09-18부터 예금금리, 이전에는 주요 재융자금리 등 BIS 선정 지표"},
    "FR": {"name": "프랑스", "currency": "EUR", "policy": "XM", "color": "#bb6296", "definition": "독일과 동일한 유로지역 ECB 정책금리. 2024-09-18 지표 정의 변경"},
    "CA": {"name": "캐나다", "currency": "CAD", "policy": "CA", "color": "#a26a39", "definition": "캐나다은행 익일물 목표금리"},
    "AU": {"name": "호주", "currency": "AUD", "policy": "AU", "color": "#44863e", "definition": "호주중앙은행 현금금리 목표"},
}

BOND_TERMS = {
    "KR": [1, 2, 3, 5, 10, 20, 30],
    "US": [1, 2, 3, 5, 7, 10, 20, 30],
    "CN": [], "JP": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 15, 20, 25, 30, 40],
    "GB": [5, 10, 20], "DE": [2, 3, 5, 10], "FR": [10],
    "CA": [2, 3, 5, 7, 10], "AU": [2, 3, 5, 10],
}


def country_name(code):
    return COUNTRIES[code]["name"]


def color_map():
    return {v["name"]: v["color"] for v in COUNTRIES.values()}


def supported_terms(country, korea_source="KTS 거래수익률 (기존)"):
    return [10] if country == "KR" and korea_source.startswith("OECD") else BOND_TERMS[country]
