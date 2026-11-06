"""Existing public API clients, retained for original KTS calculations."""

from __future__ import annotations

from datetime import date, timedelta
import time
from typing import Any
import xml.etree.ElementTree as ET

import pandas as pd
import requests

FX_URL = "https://apis.data.go.kr/B190021/mmavXrtInfoInq/getmmavXrtInfoInq"
BOND_URL = "https://apis.data.go.kr/1160100/GetBondSecuritiesInfoService_V2/getBondPriceInfo_V2"
US_TREASURY_URL = "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml"
BIS_POLICY_URL = "https://stats.bis.org/api/v2/data/dataflow/BIS/WS_CBPOL/1.0/M.KR+US"
US_TREASURY_TERMS = {1: "BC_1YEAR", 2: "BC_2YEAR", 3: "BC_3YEAR", 5: "BC_5YEAR", 7: "BC_7YEAR",
                     10: "BC_10YEAR", 20: "BC_20YEAR", 30: "BC_30YEAR"}


class DataAPIError(Exception):
    pass


def _get_json(url: str, params: dict[str, Any]) -> dict[str, Any]:
    try:
        for attempt in range(4):
            response = requests.get(url, params=params, timeout=35)
            if response.status_code != 429 or attempt == 3:
                break
            time.sleep(2 ** (attempt + 1))
        response.raise_for_status()
        data = response.json()
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else "unknown"
        if status == 429:
            raise DataAPIError("공공데이터 API의 초당 호출 한도를 넘었습니다. 잠시 후 다시 조회해 주세요.") from None
        raise DataAPIError(f"공공데이터 API HTTP {status}. 활용신청·인증키·호출량을 확인해 주세요.") from None
    except (requests.RequestException, ValueError) as exc:
        raise DataAPIError(f"공공데이터 API 응답을 읽지 못했습니다: {type(exc).__name__}") from None
    if not isinstance(data, dict):
        raise DataAPIError("공공데이터 API가 예상과 다른 형식으로 응답했습니다.")
    if "OpenAPI_ServiceResponse" in data:
        code = data["OpenAPI_ServiceResponse"].get("cmmMsgHeader", {}).get("returnReasonCode", "미상")
        raise DataAPIError(f"공공데이터포털 오류 코드 {code}. 인증키·활용 승인·호출 한도를 확인해 주세요.")
    return data


def month_starts(start: date, end: date):
    cursor = date(start.year, start.month, 1)
    while cursor <= end:
        yield cursor
        cursor = date(cursor.year + (cursor.month == 12), cursor.month % 12 + 1, 1)


def fetch_fx(key: str, start: date, end: date, base: str, quote: str) -> pd.DataFrame:
    def fetch_month(month: date) -> dict[str, Any] | None:
        data = _get_json(FX_URL, {"ServiceKey": key, "inqYm": month.strftime("%Y%m"), "cocuCd": quote})
        grid = data.get("avrgXrtGrid", [])
        if isinstance(grid, dict):
            grid = [grid]
        for item in grid or []:
            if str(item.get("baseCrcd", "")).upper() == base and str(item.get("cocuCd", "")).upper() == quote:
                value = pd.to_numeric(item.get("spcfMmavBltnXrt"), errors="coerce")
                if pd.notna(value) and value > 0:
                    return {"month": pd.Timestamp(month), "fx": float(value)}
                break
        return None

    # The provider accepts one month per request and rate limits rapid parallel calls.
    rows = []
    for index, month in enumerate(month_starts(start, end)):
        if index:
            time.sleep(1)
        row = fetch_month(month)
        if row is not None:
            rows.append(row)
    return pd.DataFrame(rows, columns=["month", "fx"]).drop_duplicates("month").sort_values("month")


def fetch_korean_bonds(key: str, start: date, end: date) -> pd.DataFrame:
    # endBasDt is exclusive according to the provider's manual.
    params = {
        "serviceKey": key,
        "beginBasDt": start.strftime("%Y%m%d"),
        "endBasDt": (end + timedelta(days=1)).strftime("%Y%m%d"),
        "mrktCtg": "KTS",
        "numOfRows": 10000,
        "resultType": "json",
    }
    rows: list[dict[str, Any]] = []
    page = 1
    while True:
        data = _get_json(BOND_URL, {**params, "pageNo": page})
        response = data.get("response", {})
        header = response.get("header", {})
        if str(header.get("resultCode")) != "00":
            raise DataAPIError(f"채권 API 오류: {header.get('resultMsg', '알 수 없는 오류')}")
        body = response.get("body", {})
        items = body.get("items") or {}
        batch = items.get("item", []) if isinstance(items, dict) else []
        if isinstance(batch, dict):
            batch = [batch]
        rows.extend(batch)
        total = int(body.get("totalCount") or 0)
        if len(rows) >= total or not batch:
            break
        page += 1
        if page > 100:
            raise DataAPIError("조회 결과가 너무 많습니다. 검색 기간을 줄여 주세요.")
    columns = ["date", "month", "term", "yield", "isinCd", "itmsNm", "itmsCtg", "trqu"]
    if not rows:
        return pd.DataFrame(columns=columns)
    frame = pd.DataFrame(rows)
    frame["date"] = pd.to_datetime(frame.get("basDt"), format="%Y%m%d", errors="coerce")
    frame["month"] = frame["date"].dt.to_period("M").dt.to_timestamp()
    frame["term"] = pd.to_numeric(frame.get("xpYrCnt"), errors="coerce")
    frame["yield"] = pd.to_numeric(frame.get("clprBnfRt"), errors="coerce")
    frame["trqu"] = pd.to_numeric(frame.get("trqu"), errors="coerce")
    frame["itmsNm"] = frame.get("itmsNm", "").fillna("").astype(str)
    frame["itmsCtg"] = frame.get("itmsCtg", "").fillna("").astype(str)
    # The KTS market also contains inflation-linked bonds; do not pool them with nominal yields.
    frame = frame[frame["itmsNm"].str.startswith("국고") & frame["term"].notna() & frame["yield"].notna()]
    # Prefer the official on-the-run benchmark when the provider marks it.
    benchmark = frame[frame["itmsCtg"] == "지표"]
    if not benchmark.empty:
        frame = benchmark
    return frame[columns].sort_values(["date", "term"])


def monthly_bond_yields(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["month", "term", "yield", "days"])
    daily = frame.groupby(["date", "month", "term"], as_index=False)["yield"].median()
    return daily.groupby(["month", "term"], as_index=False).agg(**{"yield": ("yield", "mean"), "days": ("date", "nunique")})


def _get_xml(url: str, params: dict[str, Any]) -> ET.Element:
    try:
        response = requests.get(url, params=params, timeout=40)
        response.raise_for_status()
        return ET.fromstring(response.content)
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else "unknown"
        raise DataAPIError(f"공식 금리 API HTTP {status}. 잠시 후 다시 조회해 주세요.") from None
    except (requests.RequestException, ET.ParseError):
        raise DataAPIError("공식 금리 API 응답을 읽지 못했습니다.") from None


def fetch_us_treasury(start: date, end: date) -> pd.DataFrame:
    """Daily US Treasury par yield curve, using its public XML feed."""
    ns = {"atom": "http://www.w3.org/2005/Atom",
          "m": "http://schemas.microsoft.com/ado/2007/08/dataservices/metadata",
          "d": "http://schemas.microsoft.com/ado/2007/08/dataservices"}
    rows = []
    for year in range(start.year, end.year + 1):
        root = _get_xml(US_TREASURY_URL, {"data": "daily_treasury_yield_curve", "field_tdr_date_value": year})
        for entry in root.findall("atom:entry", ns):
            props = entry.find("atom:content/m:properties", ns)
            if props is None:
                continue
            raw_date = props.findtext("d:NEW_DATE", default="", namespaces=ns)
            day = pd.to_datetime(raw_date, errors="coerce")
            if pd.isna(day) or not (start <= day.date() <= end):
                continue
            for term, field in US_TREASURY_TERMS.items():
                value = pd.to_numeric(props.findtext(f"d:{field}", default="", namespaces=ns), errors="coerce")
                if pd.notna(value):
                    rows.append({"date": day, "month": day.to_period("M").to_timestamp(),
                                 "term": term, "yield": float(value)})
    return pd.DataFrame(rows, columns=["date", "month", "term", "yield"]).sort_values(["date", "term"])


def monthly_us_yields(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["month", "term", "yield", "days"])
    return frame.groupby(["month", "term"], as_index=False).agg(**{"yield": ("yield", "mean"), "days": ("date", "nunique")})


def fetch_policy_rates(start: date, end: date) -> pd.DataFrame:
    """BIS monthly end-of-period central bank rates for KR and US."""
    root = _get_xml(BIS_POLICY_URL, {"startPeriod": start.strftime("%Y-%m"),
                                     "endPeriod": end.strftime("%Y-%m")})
    rows = []
    for series in root.iter():
        if series.tag.rsplit("}", 1)[-1] != "Series":
            continue
        country = series.get("REF_AREA")
        if country not in {"KR", "US"}:
            continue
        for obs in series:
            if obs.tag.rsplit("}", 1)[-1] != "Obs":
                continue
            month = pd.to_datetime(obs.get("TIME_PERIOD"), format="%Y-%m", errors="coerce")
            value = pd.to_numeric(obs.get("OBS_VALUE"), errors="coerce")
            if pd.notna(month) and pd.notna(value):
                rows.append({"month": month, "country": country, "rate": float(value)})
    return pd.DataFrame(rows, columns=["month", "country", "rate"]).sort_values(["month", "country"])
