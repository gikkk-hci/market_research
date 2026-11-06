"""Verified official APIs and explicitly labelled public CSV downloads."""
from datetime import date
from io import BytesIO, StringIO
import re
import xml.etree.ElementTree as ET

import pandas as pd
import requests

from cloud_apps.fx.shared.countries import COUNTRIES
from cloud_apps.fx.shared.providers.legacy import DataAPIError

COLUMNS = ["month", "country", "kind", "term", "value", "last_observed", "observations",
           "source", "source_url", "frequency", "aggregation", "definition"]
BOC_TERMS = {2: "BD.CDN.2YR.DQ.YLD", 3: "BD.CDN.3YR.DQ.YLD", 5: "BD.CDN.5YR.DQ.YLD",
             7: "BD.CDN.7YR.DQ.YLD", 10: "BD.CDN.10YR.DQ.YLD"}
BOE_TERMS = {5: "IUDSNPY", 10: "IUDMNPY", 20: "IUDLNPY"}


def empty_rates():
    result = pd.DataFrame(columns=COLUMNS)
    result["month"] = pd.Series(dtype="datetime64[ns]")
    result["last_observed"] = pd.Series(dtype="datetime64[ns]")
    result["value"] = pd.Series(dtype=float)
    result["term"] = pd.Series(dtype=int)
    return result


def request(url, params=None):
    try:
        response = requests.get(url, params=params, timeout=(10, 40),
                                headers={"User-Agent": "PublicDataResearchDashboard/1.0"})
        response.raise_for_status()
        return response
    except requests.HTTPError as exc:
        raise DataAPIError(f"공식 자료 제공처 HTTP {exc.response.status_code}. 해당 국가의 연결 상태를 확인해 주세요.") from None
    except requests.RequestException:
        raise DataAPIError("공식 자료 제공처에 연결하지 못했습니다. 잠시 후 다시 조회해 주세요.") from None


def aggregate(raw, country, kind, source, url, definition, monthly=False, aggregation=None):
    if raw.empty:
        return empty_rates()
    raw = raw.copy()
    raw["date"] = pd.to_datetime(raw["date"], errors="coerce")
    raw["value"] = pd.to_numeric(raw["value"], errors="coerce")
    raw = raw.dropna(subset=["date", "value"])
    raw = raw.drop_duplicates(["date", "term"])
    raw["month"] = raw.date.dt.to_period("M").dt.to_timestamp()
    result = raw.groupby(["month", "term"], as_index=False).agg(
        value=("value", "mean"), last_observed=("date", "max"), observations=("date", "nunique"))
    result["country"], result["kind"] = country, kind
    result["source"], result["source_url"] = source, url
    result["frequency"] = "월별" if monthly else "일별"
    result["aggregation"] = aggregation or ("원본 월별 값" if monthly else "유효 일별 관측값의 월평균")
    result["definition"] = definition
    return result[COLUMNS]


def fetch_bis(start: date, end: date, mode="월평균 (일별 집계)"):
    monthly = mode == "월말값 (기존)"
    frequency = "M" if monthly else "D"
    codes = "+".join(sorted({v["policy"] for v in COUNTRIES.values()}))
    url = f"https://stats.bis.org/api/v2/data/dataflow/BIS/WS_CBPOL/1.0/{frequency}.{codes}"
    params = {"startPeriod": start.strftime("%Y-%m") if monthly else start.isoformat(),
              "endPeriod": end.strftime("%Y-%m") if monthly else end.isoformat()}
    try:
        root = ET.fromstring(request(url, params).content)
        frames = []
        for series in root.iter():
            if series.tag.rsplit("}", 1)[-1] != "Series":
                continue
            code = series.get("REF_AREA")
            raw = pd.DataFrame([{"date": obs.get("TIME_PERIOD"), "value": obs.get("OBS_VALUE"), "term": 0}
                                for obs in series if obs.tag.rsplit("}", 1)[-1] == "Obs"])
            for country, config in COUNTRIES.items():
                if config["policy"] == code:
                    definition = config["definition"] + " | BIS 원문: " + series.get("COMPILATION", "")
                    frames.append(aggregate(raw, country, "기준금리", "BIS 정책금리 API", url,
                                            definition, monthly=monthly,
                                            aggregation="월말값(원본 월별 자료)" if monthly else None))
        return pd.concat(frames, ignore_index=True) if frames else empty_rates()
    except (ET.ParseError, ValueError, KeyError):
        raise DataAPIError("BIS 정책금리 응답 형식을 읽지 못했습니다.") from None


def fetch_canada(start, end):
    url = "https://www.bankofcanada.ca/valet/observations/" + ",".join(BOC_TERMS.values()) + "/json"
    data = request(url, {"start_date": start.isoformat(), "end_date": end.isoformat()}).json()
    rows = [{"date": obs["d"], "term": term, "value": obs[series].get("v")}
            for obs in data.get("observations", []) for term, series in BOC_TERMS.items() if series in obs]
    return aggregate(pd.DataFrame(rows), "CA", "국채 수익률", "캐나다은행 Valet API", url,
                     "선정된 벤치마크 캐나다 국채의 중간호가 종가 수익률. 잔존만기는 표기 만기의 근사값")


def fetch_uk(start, end):
    url = "https://www.bankofengland.co.uk/boeapps/database/_iadb-fromshowcolumns.asp"
    params = {"csv.x": "yes", "Datefrom": start.strftime("%d/%b/%Y"), "Dateto": "now",
              "SeriesCodes": ",".join(BOE_TERMS.values()), "CSVF": "TN", "UsingCodes": "Y", "VPD": "Y", "VFD": "N"}
    try:
        frame = pd.read_csv(BytesIO(request(url, params).content))
    except DataAPIError:
        fallback = fetch_oecd_ten_year("GB", start, end)
        fallback.attrs["source_notice"] = "영란은행 공개 CSV 연결이 실패해 OECD/FRED 월별 10년물을 별도 출처로 제공합니다. 5·20년물을 이 값으로 대체하지 않습니다."
        return fallback
    frame["DATE"] = pd.to_datetime(frame["DATE"], format="%d %b %Y", errors="coerce")
    frame = frame[frame.DATE.between(pd.Timestamp(start), pd.Timestamp(end))]
    rows = [{"date": row["DATE"], "term": term, "value": row.get(series)}
            for row in frame.to_dict("records") for term, series in BOE_TERMS.items()]
    return aggregate(pd.DataFrame(rows), "GB", "국채 수익률", "영란은행 공개 CSV", url,
                     "영국 국채 명목 파 수익률, VRP 모형으로 산출. 확인된 만기는 5·10·20년")


def parse_japanese_date(value):
    match = re.fullmatch(r"([SHR])(\d+)\.(\d+)\.(\d+)", str(value).strip())
    if match:
        era, year, month, day = match.groups()
        return pd.Timestamp(int(year) + {"S": 1925, "H": 1988, "R": 2018}[era], int(month), int(day))
    return pd.to_datetime(value, errors="coerce")


def fetch_japan(start, end):
    url = "https://www.mof.go.jp/jgbs/reference/interest_rate/data/jgbcm_all.csv"
    frame = pd.read_csv(BytesIO(request(url).content), encoding="cp932", skiprows=1, dtype=str)
    frame["date"] = frame.iloc[:, 0].map(parse_japanese_date)
    frame = frame[frame.date.between(pd.Timestamp(start), pd.Timestamp(end))]
    rows = [{"date": row["date"], "term": int(column.replace("年", "")), "value": row[column]}
            for row in frame.to_dict("records") for column in frame.columns if re.fullmatch(r"\d+年", column)]
    return aggregate(pd.DataFrame(rows), "JP", "국채 수익률", "일본 재무성 공개 CSV", url,
                     "일본 재무성 국채 콘스턴트 만기 수익률. 공식 만기별 산출값을 그대로 사용")


def fetch_germany(start, end):
    key = "D.I.ZST.ZI.EUR.S1311.B.A604.R02XX+R03XX+R05XX+R10XX.R.A.A._Z._Z.A"
    url = "https://api.statistiken.bundesbank.de/rest/data/BBSIS/" + key
    data = request(url, {"startPeriod": start.isoformat(), "endPeriod": end.isoformat(), "format": "sdmx_csv"})
    frame = pd.read_csv(BytesIO(data.content), sep=";", encoding="utf-8-sig", dtype=str)
    raw = pd.DataFrame({"date": frame["TIME_PERIOD"], "term": frame["BBK_SEIS_MATURITY"].str.extract(r"R(\d+)")[0].astype(int),
                        "value": frame["OBS_VALUE"]})
    return aggregate(raw, "DE", "국채 수익률", "독일연방은행 SDMX API", url,
                     "독일 상장 연방채 기반 Svensson 추정 금리곡선. 한국 거래수익률·미국 파 수익률과 산출 방식이 다름")


def fetch_australia(start, end):
    url = "https://www.rba.gov.au/statistics/tables/csv/f2-data.csv"
    text = request(url).content.decode("utf-8-sig")
    lines = text.splitlines()
    index = next(i for i, line in enumerate(lines) if line.startswith("Series ID,"))
    frame = pd.read_csv(StringIO("\n".join(lines[index:])), dtype=str)
    frame["date"] = pd.to_datetime(frame.iloc[:, 0], format="%d-%b-%Y", errors="coerce")
    frame = frame[frame.date.between(pd.Timestamp(start), pd.Timestamp(end))]
    terms = {2: "FCMYGBAG2D", 3: "FCMYGBAG3D", 5: "FCMYGBAG5D", 10: "FCMYGBAG10D"}
    rows = [{"date": row["date"], "term": term, "value": row.get(series)}
            for row in frame.to_dict("records") for term, series in terms.items()]
    return aggregate(pd.DataFrame(rows), "AU", "국채 수익률", "호주중앙은행 F2 공개 CSV", url,
                     "호주 국채 보간 수익률. 제공기관이 산출한 만기별 값이며 앱에서 추정하지 않음")


def fetch_oecd_ten_year(country, start, end):
    series = {"FR": "IRLTLT01FRM156N", "KR": "IRLTLT01KRM156N", "GB": "IRLTLT01GBM156N"}[country]
    url = "https://fred.stlouisfed.org/graph/fredgraph.csv"
    frame = pd.read_csv(BytesIO(request(url, {"id": series, "cosd": start.isoformat(), "coed": end.isoformat()}).content))
    raw = pd.DataFrame({"date": frame.iloc[:, 0], "term": 10, "value": frame[series]})
    return aggregate(raw, country, "국채 수익률", f"OECD / FRED 공개 CSV ({series})",
                     f"https://fred.stlouisfed.org/series/{series}",
                     "OECD 10년 만기 대표 국채 수익률의 원본 월별 자료. KTS 거래 종가 수익률과 별도 시리즈",
                     monthly=True)
