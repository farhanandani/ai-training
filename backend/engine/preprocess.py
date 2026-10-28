"""Preprocessing: history limits and censored daily demand series (TR-20, PRD 5.1)."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

MIN_TRAIN_DAYS = 280


def allowed_as_of_range(log: pd.DataFrame) -> tuple[date, date]:
    first, last = min(log["date"]), max(log["date"])
    return first + timedelta(days=MIN_TRAIN_DAYS + 30 + 14 * 7), last


def demand_series(log: pd.DataFrame, tid: str, as_of: date) -> pd.Series:
    g = log[(log["tid"] == tid) & (log["date"] <= as_of)].sort_values("date")
    idx = pd.date_range(min(g["date"]), as_of, freq="D")
    g = g.set_index(pd.to_datetime(g["date"]))
    y = g["withdrawal"].astype(float)
    # cash_out = (g["closing_balance"] == 0) & (g["withdrawal"] > 0)
    # also covers a day that starts empty (opening 0, withdrawal 0): still no real demand observed
    cash_out = g["closing_balance"] == 0
    out_of_service = (g["withdrawal"] == 0) & ((g["opening_balance"] + g["replenishment"]) > 0)
    y = y.mask(cash_out | out_of_service)
    return y.reindex(idx).astype(float).rename(tid)
