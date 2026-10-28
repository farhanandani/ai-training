"""Job runner and service orchestration (Task 12). Fast fake forecasts; no real model fits."""

import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

import engine.forecast as F
from app import jobs
from app.errors import ApiError
from app.jobs import JobRunner, cache_key
from app.services import DEFAULT_SCENARIO, SCENARIOS, Services
from app.settings import Settings
from engine import ENGINE_VERSION
from engine.calendar import HolidaysNotCovered, features
from engine.forecast import ForecastResult
from engine.models import QCOLS
from engine.preprocess import MIN_TRAIN_DAYS, demand_series

AS_OF = date(2026, 3, 6)
TIDS = [
    "TID-BAL-0010",
    "TID-BKS-0005",
    "TID-BKS-0009",
    "TID-DPK-0004",
    "TID-JKT-0001",
    "TID-JKT-0002",
    "TID-JKT-0003",
    "TID-JKT-0007",
    "TID-JKT-0008",
    "TID-TNG-0006",
]
_MULT = {"q10": 0.8, "q50": 1.0, "q80": 1.15, "q90": 1.3, "q95": 1.45}


def _fast_run_tid(tid, log, holidays, as_of):
    """Stand-in for run_tid: same short-history and holiday-coverage behaviour, weekday-mean forecast."""
    y = demand_series(log, tid, as_of)
    if len(y) < MIN_TRAIN_DAYS:
        return None
    fut = pd.date_range(pd.Timestamp(as_of) + pd.Timedelta(days=1), periods=30, freq="D")
    features(y.index.append(fut), holidays, y.index[0].date())  # raises HolidaysNotCovered
    recent = y.iloc[-28:]
    base = recent.groupby(recent.index.day_of_week).mean().fillna(recent.mean())
    q50 = np.array([float(base.get(d.day_of_week, recent.mean())) for d in fut])
    fc = pd.DataFrame(
        {c: np.rint(q50 * m).astype("int64") for c, m in _MULT.items()}, index=fut.rename("date")
    )[QCOLS]
    rows = []
    for o in (as_of - timedelta(days=44), as_of - timedelta(days=30)):
        for k in range(1, 31):
            d = o + timedelta(days=k)
            v = y.get(pd.Timestamp(d), float("nan"))
            p = float(base.get(pd.Timestamp(d).day_of_week, 0.0))
            rows.append({"origin": o, "date": d, "y": float(v), "q10": 0.8 * p, "q50": p, "q90": 1.3 * p})
    return ForecastResult(
        tid=tid,
        as_of=as_of,
        engine_version=ENGINE_VERSION,
        model="seasonal_naive",
        orders=None,
        forecast=fc,
        explanations={d.date(): [] for d in fut},
        backtest={"seasonal_naive": rows, "_failures": []},
        lebaran_check=None,
        diagnostics={"warnings": [], "fallback": False},
        fitted_q50=pd.Series(np.zeros(len(y), dtype="int64"), index=y.index, name="q50"),
    )


@pytest.fixture
def fast(monkeypatch):
    monkeypatch.setattr(F, "run_tid", _fast_run_tid)


@pytest.fixture
def runner():
    r = JobRunner(workers=2, mode="thread")
    yield r
    r.shutdown()


@pytest.fixture
def svc(store, runner, fast):
    return Services(store, runner, Settings())


def _warm(svc, as_of=AS_OF):
    _ready, _pending, job = svc.ensure_forecasts(as_of)
    if job is not None:
        assert svc.runner.wait(job, timeout=60)
    return job


# ------------------------------------------------------------------ cache key


def test_cache_key_includes_engine_version(monkeypatch):
    k1 = cache_key("TID-JKT-0001", AS_OF, "a", "b")
    assert len(k1) == 64 and k1 == cache_key("TID-JKT-0001", AS_OF, "a", "b")
    assert k1 != cache_key("TID-JKT-0001", AS_OF, "a", "c")
    assert k1 != cache_key("TID-JKT-0001", AS_OF + timedelta(days=1), "a", "b")
    monkeypatch.setattr(jobs, "ENGINE_VERSION", "999")
    assert cache_key("TID-JKT-0001", AS_OF, "a", "b") != k1


# --------------------------------------------------------------- brief tests


def test_cache_hit_no_resubmit(svc):
    ready, pending, job = svc.ensure_forecasts(AS_OF)
    assert job is not None and sorted(pending) == TIDS
    assert svc.runner.wait(job, timeout=60)
    ready, pending, job2 = svc.ensure_forecasts(AS_OF)
    assert job2 is None and pending == []
    assert sorted(ready) == TIDS
    assert all(isinstance(r, ForecastResult) for r in ready.values())


def test_edit_invalidates_only_that_tid(svc, store):
    _warm(svc)
    df = store.get_log(["TID-JKT-0001"], date(2026, 3, 1), date(2026, 3, 1)).copy()
    df["withdrawal"] *= 3
    store.upsert_log(df, "edit")
    ready, pending, job = svc.ensure_forecasts(AS_OF)
    assert pending == ["TID-JKT-0001"]
    assert job is not None
    assert sorted(ready) == [t for t in TIDS if t != "TID-JKT-0001"]


def test_duplicate_submit_joined(monkeypatch, runner):
    gate = threading.Event()
    calls = []

    def slow(tid, log_records, holiday_records, as_of_iso):
        calls.append(tid)
        gate.wait(10)
        return {"ok": None, "insufficient": True}

    monkeypatch.setattr(jobs, "_worker_run_tid", slow)
    keys = {"k1": ("TID-A", AS_OF)}
    ids = []
    threads = [
        threading.Thread(target=lambda: ids.append(runner.submit(keys, lambda t, a: ([], []))))
        for _ in range(5)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert runner.submitted == 1
    gate.set()
    for j in ids:
        assert runner.wait(j, timeout=10)
        assert runner.status(j)["total"] == 1 and runner.status(j)["done"] is True
    assert calls == ["TID-A"]


def test_job_records_holiday_coverage_failure(svc, store):
    full = store.get_holidays()
    store.put_holidays(full[full["date"] < date(2026, 3, 20)], replace=True)
    _, pending, job = svc.ensure_forecasts(AS_OF)
    assert sorted(pending) == TIDS
    assert svc.runner.wait(job, timeout=60)
    st = svc.runner.status(job)
    assert st["done"] is True and st["total"] == 10 and st["finished"] == 10
    assert sorted(f["tid"] for f in st["failed"]) == TIDS
    assert all(set(f) >= {"tid", "error"} and "HOLIDAYS_NOT_COVERED" in f["error"] for f in st["failed"])
    # failed keys are not resubmitted, the fleet still renders every TID
    ready, pending, job2 = svc.ensure_forecasts(AS_OF)
    assert job2 is None and pending == [] and ready == {}
    fleet = svc.fleet(AS_OF, 21, "p90")
    assert [a["tid"] for a in fleet["atms"]] == TIDS
    assert {a["status"] for a in fleet["atms"]} == {"forecast_failed"}
    assert all(
        a["recommended_amount"] is None and "HOLIDAYS_NOT_COVERED" in a["error"] for a in fleet["atms"]
    )
    # restoring the holidays changes the key: the forecasts run again
    store.put_holidays(full, replace=True)
    _warm(svc)
    assert {a["status"] for a in svc.fleet(AS_OF, 21, "p90")["atms"]} <= {
        "ok",
        "cash_out_risk",
        "over_stocked",
    }


def test_one_tid_failure_does_not_affect_others(svc, monkeypatch):
    def flaky(tid, log, holidays, as_of):
        if tid == "TID-JKT-0007":
            raise HolidaysNotCovered("HOLIDAYS_NOT_COVERED: holiday table does not cover 2026-04-05")
        return _fast_run_tid(tid, log, holidays, as_of)

    monkeypatch.setattr(F, "run_tid", flaky)
    job = _warm(svc)
    st = svc.runner.status(job)
    assert [f["tid"] for f in st["failed"]] == ["TID-JKT-0007"]
    rows = {a["tid"]: a for a in svc.fleet(AS_OF, 21, "p90")["atms"]}
    assert len(rows) == 10
    assert rows["TID-JKT-0007"]["status"] == "forecast_failed"
    assert all(
        r["status"] != "forecast_failed" and r["error"] is None
        for t, r in rows.items()
        if t != "TID-JKT-0007"
    )


def test_as_of_out_of_range(svc):
    with pytest.raises(ApiError) as ei:
        svc.validate_as_of(date(2025, 1, 1))
    e = ei.value
    assert e.status == 409 and e.code == "AS_OF_OUT_OF_RANGE"
    assert e.message == "as_of must be between 2025-12-10 and 2026-10-27"
    svc.validate_as_of(date(2025, 12, 10))
    svc.validate_as_of(date(2026, 10, 27))
    with pytest.raises(ApiError):
        svc.validate_as_of(date(2026, 10, 28))


# ------------------------------------------------------------ runner details


def test_timeout_recorded_as_failure(monkeypatch):
    gate = threading.Event()

    def hang(tid, log_records, holiday_records, as_of_iso):
        gate.wait(10)
        return {"ok": None, "insufficient": True}

    monkeypatch.setattr(jobs, "_worker_run_tid", hang)
    r = JobRunner(workers=1, mode="thread", timeout=0.3)
    try:
        job = r.submit({"k": ("TID-A", AS_OF)}, lambda t, a: ([], []))
        assert r.wait(job, timeout=10)
        st = r.status(job)
        assert st["done"] and st["failed"][0]["tid"] == "TID-A" and "TIMEOUT" in st["failed"][0]["error"]
    finally:
        gate.set()
        r.shutdown()


def test_status_unknown_job_is_none(runner):
    assert runner.status("j_nope") is None


def test_process_mode_real_worker_short_history():
    """Default process pool + the real top-level worker (short history returns before any fit)."""
    log = [
        {
            "tid": "TID-X",
            "date": (date(2026, 1, 1) + timedelta(days=i)).isoformat(),
            "opening_balance": 100,
            "withdrawal": 10,
            "replenishment": 0,
            "closing_balance": 90,
        }
        for i in range(20)
    ]
    hol = [{"date": "2026-12-25", "name": "Christmas Day", "type": "christmas"}]
    got = {}
    r = JobRunner(workers=1)
    try:
        job = r.submit(
            {"k": ("TID-X", date(2026, 1, 20))},
            lambda t, a: (log, hol),
            on_result=lambda key, tid, as_of, res: got.update({key: res}),
        )
        assert r.wait(job, timeout=120)
        assert r.status(job)["failed"] == []
        assert got == {"k": {"ok": None, "insufficient": True}}
    finally:
        r.shutdown()


# ------------------------------------------------------------- response shapes


def test_fleet_shape_and_kpis(svc):
    _warm(svc)
    f = svc.fleet(AS_OF, 21, "p90")
    assert set(f) == {"as_of", "h", "sl", "dataset_version", "pending_tids", "job_id", "kpis", "atms"}
    assert f["as_of"] == "2026-03-06" and f["h"] == 21 and f["pending_tids"] == [] and f["job_id"] is None
    assert set(f["kpis"]) == {"at_risk", "over_stocked", "idle_cash", "recommended_total"}
    row_keys = {
        "tid",
        "location_name",
        "location_type",
        "balance",
        "capacity",
        "days_of_cash",
        "status",
        "next_visit",
        "recommended_amount",
        "inferred_master",
        "error",
    }
    assert all(set(a) == row_keys for a in f["atms"])
    assert [a["tid"] for a in f["atms"]] == TIDS
    assert f["kpis"]["at_risk"] == sum(a["status"] == "cash_out_risk" for a in f["atms"])
    assert f["kpis"]["over_stocked"] == sum(a["status"] == "over_stocked" for a in f["atms"])
    assert f["kpis"]["recommended_total"] == sum(a["recommended_amount"] for a in f["atms"])
    assert all(isinstance(v, int) for v in f["kpis"].values())
    # TR-44: deterministic
    assert svc.fleet(AS_OF, 21, "p90") == f
    # the read records the current as_of (controller ruling for write-triggered recompute)
    assert svc.current_as_of() == AS_OF


def test_fleet_lists_only_ready_while_pending(svc, monkeypatch):
    gate = threading.Event()

    def slow(tid, log, holidays, as_of):
        if tid == "TID-JKT-0001":
            gate.wait(10)
        return _fast_run_tid(tid, log, holidays, as_of)

    monkeypatch.setattr(F, "run_tid", slow)
    _, _, job = svc.ensure_forecasts(AS_OF)
    deadline = time.time() + 30
    while svc.runner.status(job)["finished"] < 9 and time.time() < deadline:
        time.sleep(0.05)
    f = svc.fleet(AS_OF, 21, "p90")
    assert f["pending_tids"] == ["TID-JKT-0001"] and f["job_id"] == job
    assert "TID-JKT-0001" not in [a["tid"] for a in f["atms"]] and len(f["atms"]) == 9
    gate.set()
    assert svc.runner.wait(job, timeout=30)


def test_atm_shape_and_unknown(svc):
    _warm(svc)
    a = svc.atm("TID-JKT-0007", AS_OF, 21, "p90", None)
    assert set(a) == {
        "tid",
        "master",
        "status",
        "days_of_cash",
        "history",
        "forecast",
        "actual_after",
        "projection",
        "visits",
        "explanations",
        "model",
        "metrics",
        "holidays_in_view",
        "pending",
        "job_id",
        "error",
    }
    assert a["history"][0]["date"] == "2025-12-06" and a["history"][-1]["date"] == "2026-03-06"
    assert len(a["forecast"]) == 21 and set(a["forecast"][0]) == {"date", *QCOLS}
    assert len(a["actual_after"]) == 21 and a["actual_after"][0]["date"] == "2026-03-07"
    assert len(a["projection"]["current"]) == 21 and len(a["projection"]["recommended"]) == 21
    assert a["model"]["name"] == "seasonal_naive" and a["model"]["fallback"] is False
    assert set(a["metrics"]) == {"wape", "mape", "mae", "coverage", "n"}
    assert any(h["type"] == "idul_fitri" for h in a["holidays_in_view"])
    assert a == svc.atm("TID-JKT-0007", AS_OF, 21, "p90", None)
    last = svc.atm("TID-JKT-0007", date(2026, 10, 27), 14, "p90", date(2026, 10, 1))
    assert last["history"][0]["date"] == "2026-10-01"
    with pytest.raises(ApiError) as ei:
        svc.atm("TID-NOPE", AS_OF, 21, "p90", None)
    assert ei.value.status == 404 and ei.value.code == "UNKNOWN_TID"


def test_plan_shape_and_budget(svc):
    _warm(svc)
    p = svc.plan(AS_OF, 21, "p90", None)
    assert set(p) >= {
        "need_total",
        "funded_total",
        "funded_pct",
        "underfunded",
        "visits",
        "reallocation",
        "comparison",
        "pending_tids",
        "job_id",
    }
    assert p["funded_pct"] == 1.0 and p["funded_total"] == p["need_total"] > 0
    keys = [(v["tid"], v["date"]) for v in p["visits"]]
    assert keys == sorted(keys)
    assert set(p["visits"][0]) == {
        "tid",
        "date",
        "kind",
        "recommended",
        "allocated",
        "override",
        "tier1_need",
        "reason",
        "flags",
        "manual",
    }
    assert p["comparison"]["replay"]["basis"] == "true_demand"
    budget = int(p["need_total"] * 0.7)
    q = svc.plan(AS_OF, 21, "p90", budget)
    assert q["funded_total"] <= budget and q["underfunded"] >= 0
    assert isinstance(q["reallocation"], list)
    assert q == svc.plan(AS_OF, 21, "p90", budget)
    with pytest.raises(ApiError) as ei:
        svc.plan(AS_OF, 21, "p90", -1)
    assert ei.value.status == 400 and ei.value.code == "BAD_PARAMS"


def test_plan_override_marked(svc, store):
    from engine.schema import Override

    _warm(svc)
    store.put_overrides([Override("TID-JKT-0001", date(2026, 3, 10), 500_000_000)])
    p = svc.plan(AS_OF, 21, "p90", None)
    v = next(v for v in p["visits"] if v["tid"] == "TID-JKT-0001" and v["date"] == "2026-03-10")
    assert v["manual"] is True and v["override"]["amount"] == 500_000_000


def test_accuracy_shape(svc):
    _warm(svc)
    acc = svc.accuracy(AS_OF, 14)
    assert [r["tid"] for r in acc["atms"]] == TIDS
    r = acc["atms"][0]
    assert set(r) == {
        "tid",
        "status",
        "model",
        "fallback",
        "error",
        "metrics",
        "candidates",
        "lebaran_check",
        "backtest",
    }
    assert r["candidates"][0]["model"] == "seasonal_naive"
    assert all(
        0 < (date.fromisoformat(b["date"]) - date.fromisoformat(b["origin"])).days <= 14
        for b in r["backtest"]
    )
    assert isinstance(r["metrics"]["mae"], int)


def test_scenarios_and_warmup_default_first(svc):
    assert DEFAULT_SCENARIO == "pre_lebaran_2026"
    assert SCENARIOS == {
        "today": (None, 14),
        "pre_lebaran_2026": (date(2026, 3, 6), 21),
        "year_end_2025": (date(2025, 12, 15), 21),
    }
    order = svc.warmup()
    assert [sid for sid, _ in order] == ["pre_lebaran_2026", "today", "year_end_2025"]
    for _, job in order:
        assert job is None or svc.runner.wait(job, timeout=60)
    for as_of in (date(2026, 3, 6), date(2026, 10, 27), date(2025, 12, 15)):
        assert svc.ensure_forecasts(as_of)[1] == []


# ------------------------------------------------------- fix round 1: pool recovery


def _ok_worker(tid, log_records, holiday_records, as_of_iso):
    return {"ok": None, "insufficient": True}


class _FlakyPool(ThreadPoolExecutor):
    """mode: "raise" -> submit raises BrokenProcessPool; "dead" -> returns futures already broken."""

    def __init__(self, mode):
        super().__init__(max_workers=2)
        self.mode = mode

    def submit(self, fn, *args, **kwargs):
        if self.mode == "raise":
            raise BrokenProcessPool("pool is broken")
        if self.mode == "dead":
            f = Future()
            f.set_exception(BrokenProcessPool("a worker process died"))
            return f
        return super().submit(fn, *args, **kwargs)


def _factory(modes):
    made = []

    def make():
        ex = _FlakyPool(modes.pop(0) if modes else "ok")
        made.append(ex)
        return ex

    return make, made


KEYS3 = {f"k{i}": (f"TID-{i}", AS_OF) for i in range(3)}


@pytest.mark.parametrize("mode", ["raise", "dead"])
def test_broken_pool_replaced_and_retried(monkeypatch, mode):
    monkeypatch.setattr(jobs, "_worker_run_tid", _ok_worker)
    make, made = _factory([mode])
    r = JobRunner(workers=2, executor_factory=make)
    try:
        job = r.submit(KEYS3, lambda t, a: ([], []))
        assert r.wait(job, timeout=10)
        st = r.status(job)
        assert st["done"] and st["finished"] == 3 and st["failed"] == []
        assert len(made) == 2  # the broken pool was dropped and a fresh one created
        later = r.submit({"k9": ("TID-9", AS_OF)}, lambda t, a: ([], []))
        assert r.wait(later, timeout=10) and r.status(later)["failed"] == []
    finally:
        r.shutdown()
        for ex in made:
            ex.shutdown(wait=False)


def test_persistent_broken_pool_reaches_done_then_recovers(monkeypatch):
    monkeypatch.setattr(jobs, "_worker_run_tid", _ok_worker)
    make, made = _factory(["dead"] * 6)
    r = JobRunner(workers=2, executor_factory=make)
    try:
        job = r.submit(KEYS3, lambda t, a: ([], []))
        assert r.wait(job, timeout=10)
        st = r.status(job)
        assert st["done"] and sorted(f["tid"] for f in st["failed"]) == ["TID-0", "TID-1", "TID-2"]
        assert all(f["error"].startswith("POOL_FAILED") for f in st["failed"])
        assert all(r.failure(k) is None for k in KEYS3)  # retryable: not a permanent failure
        again = r.submit(KEYS3, lambda t, a: ([], []))  # pools now healthy
        assert r.wait(again, timeout=10) and r.status(again)["failed"] == []
    finally:
        r.shutdown()
        for ex in made:
            ex.shutdown(wait=False)


def test_payload_failure_recorded_and_job_done(monkeypatch, runner):
    monkeypatch.setattr(jobs, "_worker_run_tid", _ok_worker)

    def payload(tid, as_of):
        if tid == "TID-1":
            raise OSError("disk gone")
        return [], []

    job = runner.submit(KEYS3, payload)
    assert runner.wait(job, timeout=10)
    st = runner.status(job)
    assert st["done"] and [f["tid"] for f in st["failed"]] == ["TID-1"]
    assert "PAYLOAD_FAILED" in st["failed"][0]["error"]


def test_runner_reusable_after_shutdown(monkeypatch):
    monkeypatch.setattr(jobs, "_worker_run_tid", _ok_worker)
    r = JobRunner(workers=1, mode="thread")
    try:
        assert r.wait(r.submit({"a": ("TID-A", AS_OF)}, lambda t, a: ([], [])), timeout=10)
        r.shutdown()
        job = r.submit({"b": ("TID-B", AS_OF)}, lambda t, a: ([], []))
        assert r.wait(job, timeout=10) and r.status(job)["failed"] == []
        assert r._watchdog is not None and r._watchdog.is_alive()
    finally:
        r.shutdown()


def test_cache_key_matches_store_tid_hash(svc, store):
    _warm(svc)
    key = cache_key("TID-JKT-0001", AS_OF, store.tid_hash("TID-JKT-0001", AS_OF), store.holiday_hash())
    assert store.cache_get(key) is not None


def test_insufficient_history_tid_in_fleet_and_plan(svc, store):
    from engine.schema import LOG_COLS, AtmMaster

    store.put_master(
        [
            AtmMaster(
                "TID-NEW-1", "New Mall", "mall", 800_000_000, 50_000_000, 7, 100_000, 1_500_000, 700_000_000
            )
        ]
    )
    days = [AS_OF - timedelta(days=i) for i in range(99, -1, -1)]
    log = pd.DataFrame(
        {
            "tid": "TID-NEW-1",
            "date": days,
            "opening_balance": 500_000_000,
            "withdrawal": 10_000_000,
            "replenishment": 0,
            "closing_balance": 490_000_000,
        }
    )[LOG_COLS]
    store.upsert_log(log, "upload")
    _warm(svc)
    rows = {a["tid"]: a for a in svc.fleet(AS_OF, 21, "p90")["atms"]}
    assert len(rows) == 11
    new = rows["TID-NEW-1"]
    assert new["status"] == "insufficient_history"
    assert new["recommended_amount"] is None and new["days_of_cash"] is None and new["next_visit"] is None
    assert all(
        r["status"] in {"ok", "cash_out_risk", "over_stocked"} for t, r in rows.items() if t != "TID-NEW-1"
    )
    p = svc.plan(AS_OF, 21, "p90", None)
    assert not [v for v in p["visits"] if v["tid"] == "TID-NEW-1"]
    assert p["need_total"] > 0 and p["funded_pct"] == 1.0
    q = svc.plan(AS_OF, 21, "p90", p["need_total"] // 2)
    assert q["funded_total"] <= p["need_total"] // 2
