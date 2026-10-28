from datetime import date, timedelta

import pandas as pd

from engine.schedule import scheduled_visits
from engine.schema import AtmMaster

AS_OF = date(2026, 10, 27)


def _master(next_visit=None, cycle=4):
    return AtmMaster("T1", "x", "mall", 1000, 100, cycle, 50, 1, 500, next_visit_date=next_visit)


def _log(repl_dates):
    rows = [{"tid": "T1", "date": AS_OF - timedelta(days=i), "replenishment": 0} for i in range(100)]
    for r in rows:
        if r["date"] in repl_dates:
            r["replenishment"] = 500
    return pd.DataFrame(rows)


def test_schedule_ignores_emergency_refill():
    reg = [AS_OF - timedelta(days=2 + 4 * k) for k in range(20)]
    emergency = AS_OF - timedelta(days=11)  # off-phase
    assert emergency not in reg
    dates, assumed = scheduled_visits(_master(), _log(set(reg) | {emergency}), AS_OF, 10)
    assert assumed is False
    assert dates == [AS_OF + timedelta(days=2), AS_OF + timedelta(days=6), AS_OF + timedelta(days=10)]


def test_schedule_next_visit_date_override():
    dates, assumed = scheduled_visits(_master(date(2026, 10, 30)), _log(set()), AS_OF, 10)
    assert dates == [date(2026, 10, 30), date(2026, 11, 3)]
    assert assumed is False
    # anchor in the past steps forward by cycle
    dates, _ = scheduled_visits(_master(date(2026, 10, 20)), _log(set()), AS_OF, 10)
    assert dates == [date(2026, 10, 28), date(2026, 11, 1), date(2026, 11, 5)]


def test_schedule_no_replenishments_assumed():
    dates, assumed = scheduled_visits(_master(), _log(set()), AS_OF, 9)
    assert assumed is True
    assert dates[0] == AS_OF + timedelta(days=1)
    assert dates == [AS_OF + timedelta(days=d) for d in (1, 5, 9)]
