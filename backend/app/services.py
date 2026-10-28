"""Service orchestration: forecast cache/jobs (heavy layer) + planning views (light layer). ARCHITECTURE 6, 7.

Every public read returns a plain JSON-ready dict (ISO dates, int amounts, lists sorted by tid then date)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta

from app.errors import ApiError
from app.jobs import JobRunner, cache_key
from app.settings import Settings

# from app.store import Store
from app.store import Store, frame_hash
from engine.allocate import allocate, reallocation_flows
from engine.backtest import metrics
from engine.compare import build_demand_source, compare
from engine.forecast import PREFERENCE, ForecastResult
from engine.models import QCOLS
from engine.plan import AtmPlan, project_current, recommend
from engine.preprocess import allowed_as_of_range
from engine.schedule import scheduled_visits
from engine.schema import LOG_COLS, AtmMaster

SCENARIOS: dict[str, tuple[date | None, int]] = {
    "today": (None, 14),
    "pre_lebaran_2026": (date(2026, 3, 6), 21),
    "year_end_2025": (date(2025, 12, 15), 21),
}
SCENARIO_LABELS = {"today": "Today", "pre_lebaran_2026": "Pre-Lebaran 2026", "year_end_2025": "Year-end 2025"}
DEFAULT_SCENARIO = "pre_lebaran_2026"
HISTORY_DAYS = 90
_MISS = object()


@dataclass
class _Ctx:
    """Everything one read needs: forecast state + per-TID plans for the ready TIDs."""

    as_of: date
    h: int
    sl: str
    masters: dict[str, AtmMaster]
    ready: dict[str, ForecastResult | None]
    pending: list[str]
    job_id: str | None
    failed: dict[str, str]
    b0: dict[str, int]
    current: dict[str, AtmPlan]
    rec: dict[str, AtmPlan]


def _num(x, nd: int = 4):
    return None if x is None or (isinstance(x, float) and not math.isfinite(x)) else round(float(x), nd)


def _clean_metrics(m: dict | None) -> dict | None:
    """Backtest metrics with NaN -> None; MAE is an IDR amount, so int (TR-33)."""
    if m is None:
        return None
    mae = _num(m.get("mae"), 0)
    return {
        "wape": _num(m.get("wape")),
        "mape": _num(m.get("mape")),
        "mae": None if mae is None else int(mae),
        "coverage": _num(m.get("coverage")),
        "n": int(m.get("n", 0)),
    }


def _amt(x) -> int | None:
    return None if x is None or (isinstance(x, float) and not math.isfinite(x)) else round(x)


class Services:
    def __init__(self, store: Store, runner: JobRunner, settings: Settings):
        self.store = store
        self.runner = runner
        self.settings = settings
        self._memo: dict[str, ForecastResult | None] = {}
        self._range: tuple[int, tuple[date, date]] | None = None

    # ---------------------------------------------------------------- heavy layer
    # def _payload(self, tid: str, as_of: date) -> tuple[list[dict], list[dict]]:
    #     log = self.store.get_log([tid], end=as_of)[LOG_COLS]
    #     log = log.assign(date=[d.isoformat() for d in log["date"]])
    #     hol = self.store.get_holidays()
    #     hol = hol.assign(date=[d.isoformat() for d in hol["date"]])
    #     return log.to_dict("records"), hol.to_dict("records")
    @staticmethod
    def _records(df) -> list[dict]:
        return df.assign(date=[d.isoformat() for d in df["date"]]).to_dict("records")

    def _on_result(self, key: str, tid: str, as_of: date, res: dict) -> None:
        payload = {"insufficient": True} if res.get("insufficient") else res["ok"]
        self.store.cache_put(key, tid, as_of, payload)

    def _load(self, key: str):
        # if key in self._memo:
        #     return self._memo[key]
        fc = self._memo.get(key, _MISS)  # single lookup: the memo may be cleared by another thread
        if fc is not _MISS:
            return fc
        payload = self.store.cache_get(key)
        if payload is None:
            return _MISS
        fc = None if payload.get("insufficient") else ForecastResult.from_payload(payload)
        if len(self._memo) > 300:
            self._memo.clear()
        self._memo[key] = fc
        return fc

    def _collect(self, as_of: date):
        ready: dict[str, ForecastResult | None] = {}
        failed: dict[str, str] = {}
        misses: dict[str, tuple[str, date]] = {}
        # hh = self.store.holiday_hash()
        hol = self.store.get_holidays()
        hh = frame_hash(hol)  # the key hashes exactly the frames that are sent to the worker
        logs: dict[str, object] = {}
        for m in self.store.get_master():
            # key = cache_key(m.tid, as_of, self.store.tid_hash(m.tid, as_of), hh)
            log = self.store.get_log([m.tid], end=as_of)[LOG_COLS]
            key = cache_key(m.tid, as_of, frame_hash(log), hh)
            fc = self._load(key)
            if fc is not _MISS:
                ready[m.tid] = fc
            elif (err := self.runner.failure(key)) is not None:
                failed[m.tid] = err
            else:
                misses[key] = (m.tid, as_of)
                logs[m.tid] = log
        # job_id = self.runner.submit(misses, self._payload, self._on_result) if misses else None
        job_id = None
        if misses:
            hol_records = self._records(hol)
            job_id = self.runner.submit(
                misses, lambda tid, _a: (self._records(logs[tid]), hol_records), self._on_result
            )
        return ready, sorted(t for t, _ in misses.values()), job_id, failed

    def ensure_forecasts(self, as_of: date) -> tuple[dict[str, ForecastResult | None], list[str], str | None]:
        """Ready results (None = insufficient history), pending TIDs, job_id (None when nothing was submitted)."""
        ready, pending, job_id, _ = self._collect(as_of)
        return ready, pending, job_id

    def warmup(self, wait: bool = False) -> list[tuple[str, str | None]]:
        """Pre-compute the PRD 6.1 scenarios, default first (submission order = pool order)."""
        lo, hi = self._as_of_range()
        out = []
        for sid in [DEFAULT_SCENARIO, *(s for s in SCENARIOS if s != DEFAULT_SCENARIO)]:
            as_of = SCENARIOS[sid][0] or hi
            job = self.ensure_forecasts(as_of)[2] if lo <= as_of <= hi else None
            out.append((sid, job))
        if wait:
            for _, job in out:
                if job is not None:
                    self.runner.wait(job)
        return out

    # ------------------------------------------------------------------ settings
    def _as_of_range(self) -> tuple[date, date]:
        v = self.store.dataset_version()
        if self._range is None or self._range[0] != v:
            log = self.store.get_log()
            if log.empty:
                raise ApiError(409, "AS_OF_OUT_OF_RANGE", "no daily log data loaded")
            self._range = (v, allowed_as_of_range(log))
        return self._range[1]

    def validate_as_of(self, as_of: date) -> None:
        lo, hi = self._as_of_range()
        if not lo <= as_of <= hi:
            raise ApiError(
                409,
                "AS_OF_OUT_OF_RANGE",
                f"as_of must be between {lo.isoformat()} and {hi.isoformat()}",
                {"min": lo.isoformat(), "max": hi.isoformat()},
            )

    def current_as_of(self) -> date:
        """As-of of the last read/plan request (controller ruling); default scenario's as_of otherwise."""
        v = self.store.get_setting("current_as_of")
        return date.fromisoformat(v) if v else SCENARIOS[DEFAULT_SCENARIO][0]

    def _touch(self, as_of: date) -> None:
        if self.store.get_setting("current_as_of") != as_of.isoformat():
            self.store.set_setting("current_as_of", as_of.isoformat())

    def _biz(self, key: str):
        v = self.store.get_setting(key)
        return self.settings.business_defaults[key] if v is None else v

    # ---------------------------------------------------------------- light layer
    def _ctx(self, as_of: date, h: int, sl: str) -> _Ctx:
        self._touch(as_of)
        ready, pending, job_id, failed = self._collect(as_of)
        masters = {m.tid: m for m in self.store.get_master()}
        window = self.store.get_log(start=as_of - timedelta(days=HISTORY_DAYS), end=as_of)
        by_tid = {t: g for t, g in window.groupby("tid", sort=True)}
        end = as_of + timedelta(days=h)
        overrides = [o for o in self.store.get_overrides() if as_of < o.visit_date <= end]
        frac = float(self._biz("overstock_frac"))
        b0, cur, rec = {}, {}, {}
        for tid, m in masters.items():
            g = by_tid.get(tid, window.iloc[0:0])
            b0[tid] = int(g["closing_balance"].iloc[-1]) if len(g) else 0
            if tid not in ready:
                continue
            fc = ready[tid]
            dates, assumed = scheduled_visits(m, g, as_of, h)
            kw = {"overstock_frac": frac, "schedule_assumed": assumed}
            cur[tid] = project_current(m, fc, b0[tid], as_of, h, dates, **kw)
            rec[tid] = recommend(m, fc, b0[tid], as_of, h, sl, dates, overrides, **kw)
        return _Ctx(as_of, h, sl, masters, ready, pending, job_id, failed, b0, cur, rec)

    def fleet(self, as_of: date, h: int, sl: str) -> dict:
        c = self._ctx(as_of, h, sl)
        rows = []
        idle = 0.0
        for tid, m in c.masters.items():
            if tid not in c.ready and tid not in c.failed:
                continue  # pending: listed in pending_tids only
            row = {
                "tid": tid,
                "location_name": m.location_name,
                "location_type": m.location_type,
                "balance": c.b0[tid],
                "capacity": int(m.capacity),
                "days_of_cash": None,
                "status": "forecast_failed",
                "next_visit": None,
                "recommended_amount": None,
                "inferred_master": bool(m.inferred),
                "error": c.failed.get(tid),
            }
            if tid in c.ready:
                cur, rec = c.current[tid], c.rec[tid]
                row["status"], row["days_of_cash"] = cur.status, cur.days_of_cash
                if c.ready[tid] is not None:
                    loading = [v for v in rec.visits if "skip" not in v.flags]
                    row["next_visit"] = loading[0].date.isoformat() if loading else None
                    row["recommended_amount"] = int(sum(int(v.amount) for v in rec.visits))
                    # fleet idle cash: average daily p50 balance above min under the current policy (PRD 6.4)
                    idle += float((cur.projection_p50 - m.min_safe_balance).clip(min=0).mean())
            rows.append(row)
        kpis = {
            "at_risk": sum(r["status"] == "cash_out_risk" for r in rows),
            "over_stocked": sum(r["status"] == "over_stocked" for r in rows),
            "idle_cash": round(idle),
            "recommended_total": int(sum(r["recommended_amount"] or 0 for r in rows)),
        }
        return {
            "as_of": as_of.isoformat(),
            "h": h,
            "sl": sl,
            "dataset_version": self.store.dataset_version(),
            "pending_tids": c.pending,
            "job_id": c.job_id,
            "kpis": kpis,
            "atms": rows,
        }

    def atm(self, tid: str, as_of: date, h: int, sl: str, from_date: date | None) -> dict:
        if tid not in {m.tid for m in self.store.get_master()}:
            raise ApiError(404, "UNKNOWN_TID", f"unknown TID {tid}", {"tid": tid})
        c = self._ctx(as_of, h, sl)
        m = c.masters[tid]
        start = from_date or as_of - timedelta(days=HISTORY_DAYS)
        end = as_of + timedelta(days=h)
        hist = self.store.get_log([tid], start, as_of)
        after = self.store.get_log([tid], as_of + timedelta(days=1), end)
        hol = self.store.get_holidays()
        hol = hol[(hol["date"] >= start) & (hol["date"] <= end)]
        fc = c.ready.get(tid)
        cur, rec = c.current.get(tid), c.rec.get(tid)
        status = "pending" if tid in c.pending else "forecast_failed" if tid in c.failed else cur.status
        out = {
            "tid": tid,
            "master": {**m.__dict__, "next_visit_date": m.next_visit_date and m.next_visit_date.isoformat()},
            "status": status,
            "days_of_cash": cur.days_of_cash if cur is not None else None,
            "history": [
                {
                    "date": r.date.isoformat(),
                    "withdrawal": int(r.withdrawal),
                    "closing_balance": int(r.closing_balance),
                    "replenishment": int(r.replenishment),
                }
                for r in hist.itertuples()
            ],
            "forecast": [],
            "actual_after": [
                {"date": r.date.isoformat(), "withdrawal": int(r.withdrawal)} for r in after.itertuples()
            ]
            or None,
            "projection": {"current": [], "recommended": []},
            "visits": [],
            "explanations": {},
            "model": None,
            "metrics": None,
            "holidays_in_view": [
                {"date": d.isoformat(), "name": n, "type": t}
                for d, n, t in zip(hol["date"], hol["name"], hol["type"])
            ],
            "pending": tid in c.pending,
            "job_id": c.job_id,
            "error": c.failed.get(tid),
        }
        if fc is None:
            return out
        days = [as_of + timedelta(days=i + 1) for i in range(h)]
        out["forecast"] = [
            {"date": d.date().isoformat(), **{q: int(r[q]) for q in QCOLS}}
            for d, r in fc.forecast.iloc[:h].iterrows()
        ]
        out["projection"] = {
            "current": [
                {"date": d.isoformat(), "p50": int(a), "p90": int(b)}
                for d, a, b in zip(days, cur.projection_p50, cur.projection_sl)
            ],
            "recommended": [
                {"date": d.isoformat(), "p50": int(a), "sl": int(b)}
                for d, a, b in zip(days, rec.projection_p50, rec.projection_sl)
            ],
        }
        out["visits"] = [
            {
                "date": v.date.isoformat(),
                "kind": v.kind,
                "amount": int(v.amount),
                "tier1_need": int(v.tier1_need),
                "reason": v.reason,
                "flags": list(v.flags),
                "manual": bool(v.manual),
            }
            for v in rec.visits
        ]
        out["explanations"] = {d.isoformat(): list(fc.explanations.get(d, [])) for d in days}
        out["model"] = {
            "name": fc.model,
            "fallback": bool(fc.diagnostics.get("fallback", False)),
            "orders": fc.orders,
        }
        rows = fc.backtest.get(fc.model)
        out["metrics"] = _clean_metrics(metrics(rows, h)) if rows is not None else None
        return out

    def plan(self, as_of: date, h: int, sl: str, budget: int | None) -> dict:
        if budget is not None and budget < 0:
            raise ApiError(400, "BAD_PARAMS", f"budget must be >= 0, got {budget}", {"budget": budget})
        c = self._ctx(as_of, h, sl)
        tids = sorted(c.rec)
        forecasts = {t: fc for t, fc in c.ready.items() if fc is not None}
        alloc = allocate([c.rec[t] for t in tids], forecasts, sl, budget)
        ovr = {(o.tid, o.visit_date): o for o in self.store.get_overrides()}
        visits = []
        for p in alloc.plans:
            for v in p.visits:
                o = ovr.get((v.tid, v.date)) if v.manual else None
                visits.append(
                    {
                        "tid": v.tid,
                        "date": v.date.isoformat(),
                        "kind": v.kind,
                        "recommended": int(v.amount),
                        "allocated": int(v.allocated if v.allocated is not None else v.amount),
                        "override": None
                        if o is None
                        else {
                            "amount": o.amount,
                            "skipped": bool(o.skipped),
                            "moved_from": o.moved_from and o.moved_from.isoformat(),
                        },
                        "tier1_need": int(v.tier1_need),
                        "reason": v.reason,
                        "flags": list(v.flags),
                        "manual": bool(v.manual),
                    }
                )
        visits.sort(key=lambda r: (r["tid"], r["date"]))
        current = [c.current[t] for t in tids]
        demand = {t: fc.forecast["q50"].to_numpy()[:h] for t, fc in forecasts.items()}
        replay = None
        if forecasts:
            log = self.store.get_log(sorted(forecasts), as_of + timedelta(days=1), as_of + timedelta(days=h))
            td = self.store.get_true_demand()  # TR-16: only compare.py consumes it
            if td is not None:
                td = td[
                    td["tid"].isin(forecasts)
                    & (td["date"] > as_of)
                    & (td["date"] <= as_of + timedelta(days=h))
                ]
            replay = build_demand_source(log, td, forecasts, as_of, h)
            if replay is not None and not set(forecasts) <= set(replay.demand):
                replay = None  # a TID has no actuals in the window: no fair replay
        idle_rate = float(self._biz("idle_rate"))
        need = int(alloc.need_total)
        return {
            "as_of": as_of.isoformat(),
            "h": h,
            "sl": sl,
            "budget": budget,
            "dataset_version": self.store.dataset_version(),
            "pending_tids": c.pending,
            "job_id": c.job_id,
            "need_total": need,
            "funded_total": int(alloc.funded_total),
            "funded_pct": round(alloc.funded_total / need, 4) if need else 1.0,
            "unused": int(alloc.unused),
            "underfunded": int(alloc.underfunded),
            "visits": visits,
            "reallocation": reallocation_flows(current, alloc),
            "comparison": compare(current, alloc, demand, replay, idle_rate, h, as_of=as_of),
        }

    def accuracy(self, as_of: date, h: int) -> dict:
        self._touch(as_of)
        ready, pending, job_id, failed = self._collect(as_of)
        rows = []
        for tid in sorted(set(ready) | set(failed)):
            fc = ready.get(tid)
            row = {
                "tid": tid,
                "status": "forecast_failed" if tid in failed else "insufficient_history",
                "model": None,
                "fallback": False,
                "error": failed.get(tid),
                "metrics": None,
                "candidates": [],
                "lebaran_check": None,
                "backtest": [],
            }
            if fc is not None:
                bt = fc.backtest
                leb = fc.lebaran_check
                row.update(
                    status="ok",
                    model=fc.model,
                    fallback=bool(fc.diagnostics.get("fallback", False)),
                    metrics=_clean_metrics(metrics(bt[fc.model], h)) if fc.model in bt else None,
                    candidates=[
                        {"model": n, **_clean_metrics(metrics(bt[n], h))} for n in PREFERENCE if n in bt
                    ],
                    lebaran_check=None
                    if leb is None
                    else {
                        "origin": leb["origin"].isoformat(),
                        "fitri_day": leb["fitri_day"].isoformat(),
                        "metrics": _clean_metrics(leb["metrics"]),
                    },
                    backtest=[
                        {
                            "origin": r["origin"].isoformat(),
                            "date": r["date"].isoformat(),
                            "y": _amt(r["y"]),
                            "q10": _amt(r["q10"]),
                            "q50": _amt(r["q50"]),
                            "q90": _amt(r["q90"]),
                        }
                        for r in sorted(bt.get(fc.model, []), key=lambda r: (r["origin"], r["date"]))
                        if 0 < (r["date"] - r["origin"]).days <= h
                    ],
                )
            rows.append(row)
        return {
            "as_of": as_of.isoformat(),
            "h": h,
            "dataset_version": self.store.dataset_version(),
            "pending_tids": pending,
            "job_id": job_id,
            "atms": rows,
        }
