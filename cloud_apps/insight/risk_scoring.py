from __future__ import annotations

from collections import defaultdict
from statistics import median

WEIGHTS = {"qoq": 30, "yoy": 25, "anomaly": 20, "persistence": 10, "exposure": 15}
DOMAINS = ["주거 부동산", "환율·금리", "NPL", "기업금융", "해외투자", "산업재 차량"]
AGENDA_TITLES = {"주거 부동산": "지역별 주거 부동산 시장 동향 분석", "환율·금리": "환율·금리 등 주요 금융지표 분석", "NPL": "NPL·연체 및 회수 리스크 분석", "기업금융": "기업금융·차주 건전성 리스크 분석", "해외투자": "해외투자·국가 및 환율 리스크 분석", "산업재 차량": "산업재 차량·담보가치 리스크 분석"}


def _adverse_sign(direction: str) -> int:
    if direction == "lower_is_worse":
        return -1
    if direction == "higher_is_worse":
        return 1
    return 0


def _pct_change(a: float, b: float) -> float | None:
    if b == 0:
        return None
    return (a - b) / abs(b) * 100


def _percentile(value: float | None, history: list[float]) -> float | None:
    if value is None or len(history) < 3:
        return None
    ordered = sorted(history)
    below = sum(x <= value for x in ordered)
    return 100 * below / len(ordered)


def _anomaly_percentile(values: list[float], direction: str) -> float | None:
    if len(values) < 9:
        return None
    sign = _adverse_sign(direction)
    if sign == 0:
        return None
    anomalies = []
    for i in range(8, len(values)):
        prior = values[max(0, i - 12):i]
        center = median(prior)
        deviations = [abs(v - center) for v in prior]
        mad = median(deviations)
        if mad <= 1e-12:
            continue
        anomalies.append(sign * (values[i] - center) / (1.4826 * mad))
    if not anomalies:
        return None
    return _percentile(anomalies[-1], anomalies[:-1]) if len(anomalies) >= 4 else None


def analyze_metric_series(rows: list[dict], selected_quarter: str) -> list[dict]:
    groups: dict[tuple[str, str, str, str], list[dict]] = defaultdict(list)
    for row in rows:
        groups[(row.get("domain", ""), row.get("name", ""), row.get("region", "전국"), row.get("industry", "전체"))].append(row)
    results = []
    for (domain, name, region, industry), series in groups.items():
        by_q = {r["quarter"]: float(r["value"]) for r in series}
        ordered = sorted(by_q.items())
        values = [v for _, v in ordered]
        quarters = [q for q, _ in ordered]
        if selected_quarter not in by_q:
            continue
        idx = quarters.index(selected_quarter)
        current = by_q[selected_quarter]
        selected_year, selected_quarter_number = int(selected_quarter[:4]), int(selected_quarter[-1])
        expected_prev = f"{selected_year}Q{selected_quarter_number - 1}" if selected_quarter_number > 1 else f"{selected_year - 1}Q4"
        expected_yoy = f"{selected_year - 1}Q{selected_quarter_number}"
        prev_q = expected_prev if expected_prev in by_q else None
        prev_y = expected_yoy if expected_yoy in by_q else None
        direction = next((r.get("risk_direction", "") for r in series if r.get("risk_direction")), "")
        sign = _adverse_sign(direction)
        qoq = _pct_change(current, by_q[prev_q]) if prev_q else None
        yoy = _pct_change(current, by_q[prev_y]) if prev_y else None
        qoq_history, yoy_history = [], []
        if sign:
            for i in range(1, idx):
                year_i, quarter_i = int(quarters[i][:4]), int(quarters[i][-1])
                expected_i_prev = f"{year_i}Q{quarter_i - 1}" if quarter_i > 1 else f"{year_i - 1}Q4"
                if quarters[i - 1] != expected_i_prev: continue
                p = _pct_change(by_q[quarters[i]], by_q[quarters[i - 1]])
                if p is not None: qoq_history.append(sign * p)
            for i in range(4, idx):
                year_i, quarter_i = int(quarters[i][:4]), int(quarters[i][-1])
                expected_i_yoy = f"{year_i - 1}Q{quarter_i}"
                if quarters[i - 4] != expected_i_yoy: continue
                p = _pct_change(by_q[quarters[i]], by_q[quarters[i - 4]])
                if p is not None: yoy_history.append(sign * p)
        qoq_risk = sign * qoq if qoq is not None else None
        yoy_risk = sign * yoy if yoy is not None else None
        qoq_pct = _percentile(qoq_risk, qoq_history)
        yoy_pct = _percentile(yoy_risk, yoy_history)
        value_history = values[:idx + 1]
        anomaly_pct = _anomaly_percentile(value_history, direction)
        consecutive = 0
        if sign:
            for i in range(idx, 0, -1):
                year_i, quarter_i = int(quarters[i][:4]), int(quarters[i][-1])
                expected_i_prev = f"{year_i}Q{quarter_i - 1}" if quarter_i > 1 else f"{year_i - 1}Q4"
                if quarters[i - 1] != expected_i_prev: break
                change = _pct_change(by_q[quarters[i]], by_q[quarters[i - 1]])
                if change is None or sign * change <= 0: break
                consecutive += 1
        persistence_pct = min(consecutive / 4, 1) * 100 if sign else None
        components = {"qoq": qoq_pct, "yoy": yoy_pct, "anomaly": anomaly_pct, "persistence": persistence_pct}
        max_weight = sum(WEIGHTS[k] for k, v in components.items() if v is not None)
        signal_points = sum(WEIGHTS[k] * v / 100 for k, v in components.items() if v is not None)
        signal_score = (signal_points / max_weight * 100) if max_weight else None
        results.append({"domain": domain, "indicator": name, "region": region, "industry": industry, "quarter": selected_quarter, "value": current,
                        "previous_quarter": prev_q, "qoq_change_pct": qoq, "previous_year_quarter": prev_y,
                        "yoy_change_pct": yoy, "qoq_percentile": qoq_pct, "yoy_percentile": yoy_pct,
                        "anomaly_percentile": anomaly_pct, "adverse_quarters": consecutive,
                        "signal_score": signal_score, "signal_coverage": max_weight / 85 * 100 if max_weight else 0,
                        "source": series[-1].get("source", ""), "unit": series[-1].get("unit", ""),
                        "history": [{"quarter": q, "value": v} for q, v in ordered], "weights": WEIGHTS})
    return results


def score_agendas(metric_results: list[dict], exposure_rows: list[dict] | None = None, selected_quarter: str | None = None) -> list[dict]:
    exposure_rows = exposure_rows or []
    exposure_by_domain: dict[str, float] = defaultdict(float)
    exposure_buckets: dict[tuple[str, str, str], float] = defaultdict(float)
    supplied_domains: set[str] = set()
    for row in exposure_rows:
        if selected_quarter and str(row.get("quarter", "")).strip() != selected_quarter:
            continue
        try:
            domain = str(row.get("business_area", "")).strip()
            industry = str(row.get("industry", "")).strip()
            region = str(row.get("region", "")).strip()
            amount = float(row.get("exposure_amount", 0))
            if domain:
                supplied_domains.add(domain)
                exposure_by_domain[domain] += amount
                exposure_buckets[(domain, industry, region)] += amount
        except (TypeError, ValueError):
            continue
    max_exposure = max(exposure_by_domain.values(), default=0)
    by_domain: dict[str, list[dict]] = defaultdict(list)
    for row in metric_results:
        if row.get("signal_score") is not None:
            by_domain[row["domain"]].append(row)
    agendas = []
    for domain in DOMAINS:
        metrics = by_domain.get(domain, [])
        complete_metrics = [r for r in metrics if r.get("signal_coverage", 0) >= 99.9]
        usable_metrics = complete_metrics or [r for r in metrics if r.get("signal_score") is not None]
        metric_weights = []
        for metric in usable_metrics:
            # Match internally supplied portfolio exposure at the available industry/region granularity.
            candidates = [amount for (d, ind, reg), amount in exposure_buckets.items() if d == domain and
                          (not ind or ind == str(metric.get("industry", ""))) and
                          (not reg or reg == str(metric.get("region", "")))]
            metric_weights.append(max(candidates) if candidates else 1.0)
        weight_total = sum(metric_weights)
        signal = (sum(r["signal_score"] * w for r, w in zip(usable_metrics, metric_weights)) / weight_total) if weight_total else None
        exposure = exposure_by_domain.get(domain) if domain in supplied_domains else None
        exposure_points = (WEIGHTS["exposure"] * exposure / max_exposure) if exposure is not None and max_exposure > 0 else None
        signal_complete = bool(complete_metrics)
        signal_points = (85 * signal / 100) if signal is not None and signal_complete else None
        score = signal_points + exposure_points if signal_points is not None and exposure_points is not None else None
        available = (85 if signal_points is not None else 0) + (15 if exposure_points is not None else 0)
        regions = sorted({r["region"] for r in metrics})
        industries = sorted({r["industry"] for r in metrics})
        evidence = sorted(metrics, key=lambda r: (r.get("signal_score") or 0), reverse=True)
        agendas.append({"domain": domain, "title": AGENDA_TITLES[domain], "risk_score": round(score, 1) if score is not None else None,
                        "score_coverage": available, "signal_score": round(signal, 1) if signal is not None else None,
                        "signal_complete": signal_complete, "exposure_amount": exposure, "exposure_points": round(exposure_points, 1) if exposure_points is not None else None,
                        "metrics": evidence, "regions": regions, "industries": industries,
                        "status": "완료" if score is not None and available == 100 else "점수 산출 근거 부족"})
    domain_order = {name: i for i, name in enumerate(DOMAINS)}
    agendas.sort(key=lambda x: (x["risk_score"] is None, -(x["risk_score"] or 0), domain_order.get(x["domain"], 99)))
    for rank, agenda in enumerate(agendas, 1): agenda["rank"] = rank
    return agendas
