import pandas as pd


def compare_rates(rates, first, second, term):
    columns = ["month", "first", "second", "spread"]
    if rates.empty or term is None:
        empty = pd.DataFrame(columns=columns)
        empty["month"] = pd.Series(dtype="datetime64[ns]")
        return empty
    a = rates[(rates.country == first) & (rates.term == term)][["month", "value"]].rename(columns={"value": "first"})
    b = rates[(rates.country == second) & (rates.term == term)][["month", "value"]].rename(columns={"value": "second"})
    result = a.merge(b, on="month", how="inner", validate="one_to_one").sort_values("month")
    result["spread"] = result["first"] - result["second"]
    return result[columns]
