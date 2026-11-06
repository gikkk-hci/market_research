"""Caching, per-source failure isolation, and monthly data assembly."""
from datetime import date, timedelta
import time

import pandas as pd
import streamlit as st

from cloud_apps.fx.shared.countries import COUNTRIES
from cloud_apps.fx.shared.providers import international as intl
from cloud_apps.fx.shared.providers.legacy import (DataAPIError, fetch_fx, fetch_korean_bonds,
                                      fetch_us_treasury, month_starts)


@st.cache_data(ttl=3600, show_spinner=False)
def cached_policy(start, end, mode):
    return intl.fetch_bis(start, end, mode)


@st.cache_data(ttl=3600, show_spinner=False)
def cached_original(country, start, end, key):
    return fetch_korean_bonds(key, start, end) if country == "KR" else fetch_us_treasury(start, end)


@st.cache_data(ttl=3600, show_spinner=False)
def cached_country(country, start, end, korea_source):
    if country == "KR" and korea_source.startswith("OECD"):
        return intl.fetch_oecd_ten_year(country, start, end)
    functions = {"CA": intl.fetch_canada, "JP": intl.fetch_japan, "GB": intl.fetch_uk,
                 "DE": intl.fetch_germany, "AU": intl.fetch_australia,
                 "FR": lambda a, b: intl.fetch_oecd_ten_year("FR", a, b)}
    if country not in functions:
        raise DataAPIError("중국 국채의 안정적인 과거 시계열을 아직 확보하지 못했습니다. ChinaBond 공개 과거 조회가 빈 결과를 반환했습니다.")
    return functions[country](start, end)


@st.cache_data(ttl=3600, show_spinner=False)
def cached_fx_month(key, month, base, quote):
    # Cache hits skip the delay and network call; first-time requests stay below the portal's rate limit.
    time.sleep(1)
    return fetch_fx(key, month, month, base, quote)


def load_fx(key, start, end, base, quote):
    columns = ["month", "fx"]
    if base == quote:
        return pd.DataFrame(columns=columns), "두 국가가 같은 통화를 사용하므로 환율 상관분석을 제공하지 않습니다."
    if not key:
        return pd.DataFrame(columns=columns), "환율 조회에는 공공데이터포털 인증키가 필요합니다. 금리 자료는 계속 조회할 수 있습니다."
    latest = date.today().replace(day=1) - timedelta(days=1)
    frames, issue = [], ""
    for month in month_starts(start, min(end, latest)):
        try:
            frames.append(cached_fx_month(key, month, base, quote))
        except DataAPIError as exc:
            issue = f"{month:%Y-%m} 환율 조회 중단: {exc} 앞서 정상 조회한 월만 표시합니다."
            break
        except (ValueError, KeyError, TypeError, AttributeError):
            issue = f"{month:%Y-%m} 환율 응답 형식을 읽지 못했습니다. 앞서 정상 조회한 월만 표시합니다."
            break
    result = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=columns)
    return result.sort_values("month"), issue


def original_bonds(country, start, end, key):
    if country == "KR" and not key:
        raise DataAPIError("한국 KTS 국채 조회에는 공공데이터포털 인증키가 필요합니다.")
    chunks = [cached_original(country, max(start, date(y, 1, 1)), min(end, date(y, 12, 31)), key)
              for y in range(start.year, end.year + 1)]
    chunks = [frame for frame in chunks if not frame.empty]
    if not chunks:
        return intl.empty_rates()
    frame = pd.concat(chunks, ignore_index=True)
    # Keep the existing KTS daily-median then monthly-mean calculation.
    raw = frame.groupby(["date", "term"], as_index=False)["yield"].median().rename(columns={"yield": "value"})
    if country == "KR":
        return intl.aggregate(raw, country, "국채 수익률", "금융위원회 KTS API",
                              "https://apis.data.go.kr/1160100/GetBondSecuritiesInfoService_V2/getBondPriceInfo_V2",
                              "KTS 일반 국고채 지표 종가 수익률. 일별 동일 만기 중앙값 후 월평균. 물가연동채 제외")
    return intl.aggregate(raw, country, "국채 수익률", "미국 재무부 XML API",
                          "https://home.treasury.gov/treasury-daily-interest-rate-xml-feed",
                          "미국 재무부 명목 국채 파 수익률곡선의 일별 만기별 값")


def load_rates(countries, kind, start, end, key="", policy_mode="월평균 (일별 집계)",
               korea_source="KTS 거래수익률 (기존)"):
    frames, issues = [], []
    if kind == "기준금리":
        try:
            all_rates = cached_policy(start, end, policy_mode)
            for country in countries:
                frame = all_rates[all_rates.country == country]
                if frame.empty:
                    issues.append({"국가": COUNTRIES[country]["name"], "내용": "선택 기간의 BIS 정책금리 자료가 없습니다."})
                frames.append(frame)
        except DataAPIError as exc:
            issues.append({"국가": "BIS", "내용": str(exc)})
    else:
        for country in countries:
            try:
                frame = (original_bonds(country, start, end, key)
                         if country == "US" or (country == "KR" and not korea_source.startswith("OECD"))
                         else cached_country(country, start, end, korea_source))
                if frame.empty:
                    issues.append({"국가": COUNTRIES[country]["name"], "내용": "선택 기간의 국채 자료가 없습니다."})
                if frame.attrs.get("source_notice"):
                    issues.append({"국가": COUNTRIES[country]["name"], "내용": frame.attrs["source_notice"]})
                frames.append(frame)
            except DataAPIError as exc:
                issues.append({"국가": COUNTRIES[country]["name"], "내용": str(exc)})
            except (ValueError, KeyError, TypeError, StopIteration):
                issues.append({"국가": COUNTRIES[country]["name"], "내용": "원본 자료 형식을 읽지 못했습니다. 제공기관 형식 변경 여부를 확인해야 합니다."})
    return (pd.concat(frames, ignore_index=True) if frames else intl.empty_rates()), issues
