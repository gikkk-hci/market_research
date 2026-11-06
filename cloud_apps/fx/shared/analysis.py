"""Calendar-aware checks shared by the two dashboard pages."""

from datetime import date

import pandas as pd


def coverage_table(start: date, end: date, fx: pd.DataFrame,
                   kr_months: pd.Series, us_months: pd.Series,
                   labels=("한국 금리", "미국 금리")) -> pd.DataFrame:
    months = pd.date_range(date(start.year, start.month, 1),
                           date(end.year, end.month, 1), freq="MS")
    result = pd.DataFrame({"month": months})
    for label, values in (("환율", fx["month"]), (labels[0], kr_months), (labels[1], us_months)):
        result[label] = result["month"].isin(pd.to_datetime(values))
    result["공통 관측"] = result[["환율", *labels]].all(axis=1)
    return result


def consecutive_month_changes(joined: pd.DataFrame) -> pd.DataFrame:
    ordered = joined.sort_values("month").copy()
    month_number = ordered["month"].dt.year * 12 + ordered["month"].dt.month
    ordered["fx_change"] = ordered["fx"].pct_change() * 100
    ordered["spread_change"] = ordered["spread"].diff()
    return ordered.loc[month_number.diff().eq(1),
                       ["month", "fx_change", "spread_change"]].dropna()


def rolling_level_correlation(joined: pd.DataFrame, start: date, end: date,
                              window: int = 24, min_periods: int = 18) -> pd.DataFrame:
    months = pd.date_range(date(start.year, start.month, 1),
                           date(end.year, end.month, 1), freq="MS")
    full = joined.set_index("month")[["fx", "spread"]].reindex(months)
    values = full["fx"].rolling(window, min_periods=min_periods).corr(full["spread"])
    return pd.DataFrame({"month": months, "correlation": values.to_numpy()}).dropna()
