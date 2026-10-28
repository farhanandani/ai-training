"""Calendar regressors known in advance (TR-21, PRD 5.2)."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

FEATURE_COLS = [
    "dow_1",
    "dow_2",
    "dow_3",
    "dow_4",
    "dow_5",
    "dow_6",
    "payday",
    "fitri_ramadan",
    "fitri_thr",
    "fitri_ramp_far",
    "fitri_ramp_near",
    "fitri_holiday",
    "fitri_return",
    "year_end",
    "new_year_day",
    "pre_holiday",
    "holiday",
    "trend",
]

# bucket name -> (min, max) inclusive of days-to-Idul-Fitri-day-1
_FITRI_BUCKETS = {
    "fitri_ramadan": (21, 30),
    "fitri_thr": (11, 20),
    "fitri_ramp_far": (6, 10),
    "fitri_ramp_near": (1, 5),
    "fitri_holiday": (-6, 0),
    "fitri_return": (-13, -7),
}


class HolidaysNotCovered(ValueError):
    code = "HOLIDAYS_NOT_COVERED"


def fitri_days(holidays: pd.DataFrame) -> list[date]:
    """Day 1 of each Idul Fitri: an idul_fitri date whose previous day is not idul_fitri."""
    ds = set(holidays.loc[holidays["type"] == "idul_fitri", "date"])
    return sorted(d for d in ds if d - timedelta(days=1) not in ds)


def features(index: pd.DatetimeIndex, holidays: pd.DataFrame, series_start: date) -> pd.DataFrame:
    days = [d.date() for d in index]
    if days:
        last = max(days)
        hol_dates = list(holidays["date"])
        ny_after = bool(holidays.loc[holidays["type"] == "new_year", "date"].gt(last).any())
        if not hol_dates or (max(hol_dates) < last and not ny_after):
            raise HolidaysNotCovered(f"HOLIDAYS_NOT_COVERED: holiday table does not cover {last.isoformat()}")
    out = pd.DataFrame(0.0, index=index, columns=FEATURE_COLS)
    dow = index.day_of_week
    for k in range(1, 7):
        out[f"dow_{k}"] = (dow == k).astype(float)
    dom = index.day
    out["payday"] = ((dom >= 25) | (dom <= 3)).astype(float)

    fitri = fitri_days(holidays)
    to_fitri = [[(f - d).days for f in fitri] for d in days]
    for name, (lo, hi) in _FITRI_BUCKETS.items():
        out[name] = [float(any(lo <= t <= hi for t in ts)) for ts in to_fitri]
    in_fitri = out[list(_FITRI_BUCKETS)].sum(axis=1) > 0

    out["year_end"] = ((index.month == 12) & (dom >= 20)).astype(float)
    by_type: dict[str, set[date]] = {t: set(g["date"]) for t, g in holidays.groupby("type")}
    out["new_year_day"] = [float(d in by_type.get("new_year", set())) for d in days]
    national = by_type.get("national", set())
    out["pre_holiday"] = [float((d + timedelta(days=1)) in national) for d in days]
    hol = national | by_type.get("christmas", set()) | by_type.get("cuti_bersama", set())
    out["holiday"] = [float(d in hol) for d in days]
    out.loc[in_fitri, "holiday"] = 0.0
    out["trend"] = np.array([(d - series_start).days / 365 for d in days], dtype=float)
    return out[FEATURE_COLS]
