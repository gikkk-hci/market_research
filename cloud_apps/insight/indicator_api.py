from __future__ import annotations

from datetime import date
from typing import Any
import re

import requests

TIMEOUT = 25


def quarter_sequence(start_year: int, start_quarter: int, end_year: int, end_quarter: int) -> list[str]:
    out = []
    year, quarter = start_year, start_quarter
    while (year, quarter) <= (end_year, end_quarter):
        out.append(f"{year}Q{quarter}")
        quarter += 1
        if quarter == 5:
            year += 1
            quarter = 1
    return out


def shift_quarter(year: int, quarter: int, offset: int) -> tuple[int, int]:
    absolute = year * 4 + (quarter - 1) + offset
    return absolute // 4, absolute % 4 + 1


def period_to_quarter(value: Any) -> str | None:
    s = str(value or "").strip()
    m = re.search(r"(20\d{2})\s*[Qq]\s*([1-4])", s)
    if not m:
        m = re.search(r"(20\d{2})\s*년?\s*([1-4])\s*분기", s)
    if m:
        return f"{m.group(1)}Q{m.group(2)}"
    m = re.search(r"(20\d{2})\s*[-/.]?\s*(0?[1-9]|1[0-2])(?:월)?", s)
    if m:
        month = int(m.group(2))
        return f"{m.group(1)}Q{(month - 1) // 3 + 1}"
    m = re.fullmatch(r"(20\d{2})", s)
    if m:
        return f"{m.group(1)}Q4"
    return None


def numeric(value: Any) -> float | None:
    if value is None:
        return None
    s = str(value).strip().replace(",", "").replace("%", "")
    if not s or s in {"-", "…", "N/A", "nan", "None"}:
        return None
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def _records(payload: Any) -> list[dict]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for value in payload.values():
            if isinstance(value, list):
                nested = [x for x in value if isinstance(x, dict)]
                if nested:
                    return nested
            if isinstance(value, dict):
                nested = _records(value)
                if nested:
                    return nested
    return []


def _get_json(url: str, params: dict, headers: dict | None = None) -> Any:
    response = requests.get(url, params=params, headers=headers, timeout=TIMEOUT)
    response.raise_for_status()
    try:
        payload = response.json()
    except requests.exceptions.JSONDecodeError as exc:
        raise ValueError("API 응답이 JSON 형식이 아닙니다. 인증키, 요청 조건, 응답 형식을 확인하세요.") from exc
    if isinstance(payload, dict) and payload.get("RESULT"):
        result = payload["RESULT"]
        raise ValueError(f"API 오류: {result.get('MESSAGE', result)}")
    if isinstance(payload, list) and payload and isinstance(payload[0], dict) and payload[0].get("err"): 
        raise ValueError(f"API 오류: {payload[0].get('errMsg', payload[0])}")
    return payload


def _fetch_ecos(config: dict, api_key: str, start: str, end: str) -> list[dict]:
    stat_code = config.get("stat_code", "").strip()
    item_code = config.get("item_code", "").strip()
    cycle = config.get("cycle", "M").strip()
    if not stat_code or not item_code:
        raise ValueError("ECOS stat_code와 item_code를 indicator_catalog.json에 입력해야 합니다.")
    start_code = start if cycle.upper() == "Q" else start[:4] + "01"
    end_code = end if cycle.upper() == "Q" else end[:4] + "12"
    url = f"https://ecos.bok.or.kr/api/StatisticSearch/{api_key}/json/kr/1/1000/{stat_code}/{cycle}/{start_code}/{end_code}/{item_code}"
    payload = _get_json(url, {})
    rows = payload.get("StatisticSearch", {}).get("row", []) if isinstance(payload, dict) else []
    if isinstance(payload, dict) and payload.get("RESULT"):
        raise ValueError(f"ECOS: {payload['RESULT'].get('MESSAGE', '요청 오류')}")
    return [{"period": r.get("TIME"), "value": r.get("DATA_VALUE"), "region": r.get("ITEM_NAME1", "전국"), "industry": r.get("ITEM_NAME2", "전체"), "source": "한국은행 ECOS", "indicator": config.get("name", stat_code)} for r in rows]


def _fetch_rone(config: dict, api_key: str, start: str, end: str) -> list[dict]:
    statbl = config.get("statbl_id", "").strip()
    region = config.get("region_id", "").strip()
    item = config.get("item_id", "").strip()
    if not statbl or not region or not item:
        raise ValueError("R-ONE statbl_id, region_id, item_id가 필요합니다. 통계코드 검색에서 선택하세요.")
    params = {"STATBL_ID": statbl, "DTACYCLE_CD": config.get("cycle", "MM"), "CLS_ID": region, "ITM_ID": item,
              "START_WRTTIME": start[:4], "END_WRTTIME": end[:4], "Type": "json", "KEY": api_key}
    payload = _get_json("https://www.reb.or.kr/r-one/openapi/SttsApiTblData.do", params)
    blocks = payload.get("SttsApiTblData", []) if isinstance(payload, dict) else []
    rows = []
    for block in blocks:
        if isinstance(block, dict) and isinstance(block.get("row"), list):
            rows.extend(block["row"])
    return [{"period": r.get("WRTTIME_DESC") or r.get("WRTTIME_IDTFR_ID"), "value": r.get("DTA_VAL"),
             "region": r.get("CLS_FULLNM") or r.get("CLS_NM", "미분류"), "industry": r.get("ITM_NM", "전체"),
             "source": "한국부동산원 R-ONE", "indicator": config.get("name", statbl)} for r in rows]


def _fetch_kosis(config: dict, api_key: str, start: str, end: str) -> list[dict]:
    required = ("org_id", "table_id", "item_id", "class1_id", "frequency")
    missing = [key for key in required if not str(config.get(key, "")).strip()]
    if missing:
        raise ValueError("KOSIS 설정에 미입력 항목이 있습니다: " + ", ".join(missing))
    frequency = config["frequency"]
    start_period = start if frequency.upper() == "Q" else start[:4] + "01"
    end_period = end if frequency.upper() == "Q" else end[:4] + "12"
    params = {"method": "getList", "apiKey": api_key, "orgId": config["org_id"], "tblId": config["table_id"],
              "itmId": config["item_id"], "objL1": config["class1_id"], "prdSe": frequency,
              "startPrdDe": start_period, "endPrdDe": end_period, "format": "json", "jsonVD": "Y"}
    for i in range(2, 9):
        key = f"class{i}_id"
        if config.get(key):
            params[f"objL{i}"] = config[key]
    payload = _get_json("https://kosis.kr/openapi/Param/statisticsParameterData.do", params)
    rows = _records(payload)
    return [{"period": r.get("PRD_DE"), "value": r.get("DT"), "region": r.get("C1_NM", "전국"),
             "industry": r.get("C2_NM", "전체"), "source": "KOSIS 국가통계포털", "indicator": config.get("name", config["table_id"])} for r in rows]


def fetch_indicator(config: dict, keys: dict[str, str], start: str, end: str) -> list[dict]:
    provider = config.get("provider", "").lower()
    if provider == "ecos":
        raw = _fetch_ecos(config.get("params", {}), keys.get("ecos", ""), start, end)
    elif provider in {"r-one", "rone"}:
        raw = _fetch_rone(config.get("params", {}), keys.get("r-one", ""), start, end)
    elif provider == "kosis":
        raw = _fetch_kosis(config.get("params", {}), keys.get("kosis", ""), start, end)
    else:
        raise ValueError(f"지원하지 않는 API 제공처: {provider}")
    aggregation = config.get("aggregation", "last")
    grouped: dict[str, list[dict]] = {}
    for row in raw:
        quarter = period_to_quarter(row.get("period"))
        value = numeric(row.get("value"))
        if quarter and value is not None and start <= quarter <= end:
            grouped.setdefault(quarter, []).append({**row, "quarter": quarter, "value": value})
    out = []
    for quarter, values in sorted(grouped.items()):
        nums = [r["value"] for r in values]
        if aggregation == "sum": value = sum(nums)
        elif aggregation == "mean": value = sum(nums) / len(nums)
        elif aggregation == "max": value = max(nums)
        elif aggregation == "min": value = min(nums)
        else: value = values[-1]["value"]
        out.append({**values[-1], "quarter": quarter, "value": value, "observation_count": len(values),
                    "aggregation": aggregation, "domain": config.get("domain", "미분류"), "name": config.get("name", "미지정 지표"),
                    "risk_direction": config.get("risk_direction", ""), "source_url": config.get("source_url", "")})
    if not out:
        raise ValueError("선택 기간에 해당하는 숫자 시계열이 없습니다. 통계표 코드·기간·항목을 확인하세요.")
    return out


def fetch_catalog(catalog: dict, keys: dict[str, str], start: str, end: str) -> tuple[list[dict], list[dict]]:
    results, errors = [], []
    for config in catalog.get("indicators", []):
        if not config.get("enabled"):
            continue
        provider = config.get("provider", "").lower()
        key_name = "r-one" if provider in {"r-one", "rone"} else provider
        if not keys.get(key_name):
            errors.append({"indicator": config.get("name", "지표"), "domain": config.get("domain", ""), "error": f"{key_name.upper()} API 키가 없습니다."})
            continue
        try:
            results.extend(fetch_indicator(config, keys, start, end))
        except (ValueError, requests.RequestException, KeyError, TypeError) as exc:
            # requests exceptions can contain the full URL, including API keys.
            from urllib.parse import quote, quote_plus
            message = str(exc)
            for key in keys.values():
                if key:
                    for value in (key, quote(key, safe=""), quote_plus(key)):
                        message = message.replace(value, "[인증키 숨김]")
            errors.append({"indicator": config.get("name", "지표"), "domain": config.get("domain", ""), "error": message})
    return results, errors
