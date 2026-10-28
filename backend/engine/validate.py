"""Log validation, master inference, censored demand series (TR-13, TR-20, PRD 4.1, 5.1)."""

from __future__ import annotations

import itertools
import math
from datetime import timedelta
from statistics import median

import pandas as pd

from engine.schema import AtmMaster, Issue

_CAP_STEP = 50_000_000
_DEFAULT_COST = 1_500_000
_DEFAULT_CYCLE = 7


def validate_log(log: pd.DataFrame, master: list[AtmMaster]) -> list[Issue]:
    issues: list[Issue] = []
    known = {m.tid for m in master}
    for tid, g in log.groupby("tid", sort=True):
        tid = str(tid)
        g = g.sort_values("date")
        if tid not in known:
            issues.append(
                Issue(
                    "warning",
                    "UNKNOWN_TID",
                    f"{tid} is not in the ATM master; values were inferred, please review",
                    tid,
                )
            )
        bad = g[g["closing_balance"] != g["opening_balance"] - g["withdrawal"] + g["replenishment"]]
        for r in bad.itertuples():
            issues.append(
                Issue(
                    "warning",
                    "BALANCE_IDENTITY",
                    f"{tid} {r.date}: closing {r.closing_balance} != opening - withdrawal + replenishment",
                    tid,
                    r.date,
                )
            )
        dates = list(g["date"])
        opening = list(g["opening_balance"])
        closing = list(g["closing_balance"])
        for i in range(1, len(dates)):
            gap = (dates[i] - dates[i - 1]).days
            if gap == 1 and opening[i] != closing[i - 1]:
                issues.append(
                    Issue(
                        "warning",
                        "CONTINUITY",
                        f"{tid} {dates[i]}: opening {opening[i]} != previous closing {closing[i - 1]}",
                        tid,
                        dates[i],
                    )
                )
            elif gap > 1:
                a = dates[i - 1] + timedelta(days=1)
                b = dates[i] - timedelta(days=1)
                issues.append(
                    Issue(
                        "warning",
                        "MISSING_DATES",
                        f"{tid} has no rows for {a.isoformat()} to {b.isoformat()} ({gap - 1} days)",
                        tid,
                        a,
                    )
                )
    return issues


def infer_master(log: pd.DataFrame, tid: str, fleet: list[AtmMaster]) -> AtmMaster:
    g = log[log["tid"] == tid].sort_values("date")
    max_bal = max(int(g["opening_balance"].max()), int(g["closing_balance"].max()))
    capacity = max(_CAP_STEP, math.ceil(max_bal / _CAP_STEP) * _CAP_STEP)
    min_safe = round(float(g["withdrawal"].median()))
    rep = g[g["replenishment"] > 0]
    rep_dates = list(rep["date"])
    gaps = [(b - a).days for a, b in itertools.pairwise(rep_dates)]
    cycle = round(median(gaps)) if gaps else _DEFAULT_CYCLE
    fill = round(float(rep["closing_balance"].median())) if len(rep) else capacity
    cost = round(median([m.cost_per_visit for m in fleet])) if fleet else _DEFAULT_COST
    return AtmMaster(
        tid=tid,
        location_name=tid,
        location_type="unknown",
        capacity=capacity,
        min_safe_balance=min_safe,
        replenish_cycle_days=max(1, cycle),
        denomination=100_000,
        cost_per_visit=cost,
        current_fill_level=fill,
        next_visit_date=None,
        inferred=True,
    )
