"""Fixed replenishment schedule inference (TR-29, PRD 6.1)."""

from __future__ import annotations

from collections import Counter
from datetime import date, timedelta

import pandas as pd

from engine.schema import AtmMaster


def scheduled_visits(master: AtmMaster, log: pd.DataFrame, as_of: date, h: int) -> tuple[list[date], bool]:
    """Visit dates in (as_of, as_of+h] and whether the schedule was assumed."""
    cycle = master.replenish_cycle_days
    end = as_of + timedelta(days=h)
    if master.next_visit_date is not None:
        d = master.next_visit_date
        if d <= as_of:
            d += timedelta(days=cycle * ((as_of - d).days // cycle + 1))
        out = []
        while d <= end:
            out.append(d)
            d += timedelta(days=cycle)
        return out, False

    window = log[(log["date"] > as_of - timedelta(days=90)) & (log["date"] <= as_of)]
    repl = sorted(window.loc[window["replenishment"] > 0, "date"])
    assumed = not repl
    if assumed:
        phase = (as_of + timedelta(days=1)).toordinal() % cycle
    else:
        counts = Counter(d.toordinal() % cycle for d in repl)
        top = max(counts.values())
        tied = {p for p, c in counts.items() if c == top}
        phase = next(d.toordinal() % cycle for d in reversed(repl) if d.toordinal() % cycle in tied)
    out = []
    d = as_of + timedelta(days=1)
    while d <= end:
        if d.toordinal() % cycle == phase:
            out.append(d)
        d += timedelta(days=1)
    return out, assumed
