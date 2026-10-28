"""Forecast job runner: process pool, cache keys, join-on-duplicate, timeouts (ARCHITECTURE 4.2, 7; TR-38..TR-41).

Only stdlib + `engine.ENGINE_VERSION` are imported at module level, so a spawned worker runs
`_init_worker` (TR-40 thread caps) before numpy/statsmodels are loaded by `_worker_run_tid`."""

from __future__ import annotations

import hashlib
import os
import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import Future, ProcessPoolExecutor, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from engine import ENGINE_VERSION

TIMEOUT_S = 120.0
JOB_TTL_S = 600.0
_THREAD_VARS = ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")


def cache_key(tid: str, as_of: date, tid_hash: str, holiday_hash: str) -> str:
    """sha256(tid, as_of, tid_data_hash, holiday_hash, ENGINE_VERSION) (ARCHITECTURE 4.2)."""
    raw = f"{tid}|{as_of.isoformat()}|{tid_hash}|{holiday_hash}|{ENGINE_VERSION}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _init_worker() -> None:
    for v in _THREAD_VARS:  # TR-40
        os.environ[v] = "1"


def _worker_run_tid(tid: str, log_records: list[dict], holiday_records: list[dict], as_of_iso: str) -> dict:
    """Runs in a worker process. Plain records in, plain dict out (nothing heavy crosses the boundary)."""
    import pandas as pd

    from engine import forecast
    from engine.schema import LOG_COLS

    try:
        log = pd.DataFrame(log_records, columns=LOG_COLS)
        log["date"] = [date.fromisoformat(d) for d in log["date"]]
        hol = pd.DataFrame(holiday_records, columns=["date", "name", "type"])
        hol["date"] = [date.fromisoformat(d) for d in hol["date"]]
        res = forecast.run_tid(tid, log, hol, date.fromisoformat(as_of_iso))
    except Exception as e:  # noqa: BLE001  reported per TID; other TIDs keep working (TR-41)
        return {"error": str(e), "code": getattr(e, "code", "FORECAST_FAILED")}
    if res is None:
        return {"ok": None, "insufficient": True}
    return {"ok": res.to_payload()}


PayloadFn = Callable[[str, date], tuple[list[dict], list[dict]]]
ResultFn = Callable[[str, str, date, dict], None]


@dataclass
class _Job:
    keys: dict[str, tuple[str, date]]
    created: float = field(default_factory=time.monotonic)


class JobRunner:
    """One executor + an in-memory registry keyed by cache_key (ARCHITECTURE 7).

    mode="process" (default, production) uses a ProcessPoolExecutor with the TR-40 initializer;
    mode="thread" runs the same worker function in threads (tests: monkeypatched fakes stay visible)."""

    def __init__(
        self,
        workers: int,
        *,
        mode: Literal["process", "thread"] = "process",
        timeout: float = TIMEOUT_S,
        job_ttl: float = JOB_TTL_S,
    ):
        self.workers = max(1, int(workers))
        self.mode = mode
        self.timeout = timeout
        self.job_ttl = job_ttl
        self.submitted = 0  # futures actually created (joined keys are not counted)
        self._executor = None
        self._lock = threading.RLock()
        self._jobs: dict[str, _Job] = {}
        self._inflight: dict[str, Future] = {}
        self._started: dict[str, float] = {}
        self._done: dict[str, str | None] = {}  # key -> None (ok) | error message
        self._cond = threading.Condition(self._lock)
        self._stop = threading.Event()
        self._watchdog: threading.Thread | None = None

    # ------------------------------------------------------------- executor
    def _pool(self):
        if self._executor is None:
            if self.mode == "thread":
                self._executor = ThreadPoolExecutor(max_workers=self.workers, thread_name_prefix="fc")
            else:
                self._executor = ProcessPoolExecutor(max_workers=self.workers, initializer=_init_worker)
            self._watchdog = threading.Thread(target=self._watch, name="fc-watchdog", daemon=True)
            self._watchdog.start()
        return self._executor

    def shutdown(self) -> None:
        self._stop.set()
        with self._lock:
            ex, self._executor = self._executor, None
        if ex is not None:
            ex.shutdown(wait=False, cancel_futures=True)

    # --------------------------------------------------------------- public
    def submit(
        self, keys: dict[str, tuple[str, date]], payload_fn: PayloadFn, on_result: ResultFn | None = None
    ) -> str:
        """Start a job over `keys` (cache_key -> (tid, as_of)). Keys already running are joined; when all of
        them are running inside one live job, that job's id is returned (a polling UI keeps its job_id)."""
        job_id = "j_" + uuid.uuid4().hex[:12]
        with self._lock:
            self._prune()
            if keys and all(k in self._inflight for k in keys):
                for jid in reversed(list(self._jobs)):
                    if set(keys) <= set(self._jobs[jid].keys):
                        return jid
            self._jobs[job_id] = _Job(dict(keys))
            for key, (tid, as_of) in keys.items():
                if key in self._inflight:
                    continue
                self._done.pop(key, None)
                log_records, holiday_records = payload_fn(tid, as_of)
                fut = self._pool().submit(
                    _worker_run_tid, tid, log_records, holiday_records, as_of.isoformat()
                )
                self.submitted += 1
                self._inflight[key] = fut
                fut.add_done_callback(lambda f, k=key, t=tid, a=as_of: self._finish(k, t, a, f, on_result))
        return job_id

    def status(self, job_id: str) -> dict | None:
        """TR-38 shape; None when the job is unknown or expired."""
        with self._lock:
            self._prune()
            job = self._jobs.get(job_id)
            if job is None:
                return None
            resolved = [k for k in job.keys if k in self._done and k not in self._inflight]
            failed = sorted(
                (
                    {"tid": job.keys[k][0], "error": self._done[k]}
                    for k in resolved
                    if self._done[k] is not None
                ),
                key=lambda f: f["tid"],
            )
            return {
                "job_id": job_id,
                "done": len(resolved) == len(job.keys),
                "total": len(job.keys),
                "finished": len(resolved),
                "failed": failed,
            }

    def failure(self, key: str) -> str | None:
        """The error of a finished-and-failed key (failed keys are not resubmitted until the key changes)."""
        with self._lock:
            return None if key in self._inflight else self._done.get(key)

    def wait(self, job_id: str, timeout: float | None = None) -> bool:
        end = None if timeout is None else time.monotonic() + timeout
        with self._cond:
            while True:
                st = self.status(job_id)
                if st is None or st["done"]:
                    return st is not None
                left = None if end is None else end - time.monotonic()
                if left is not None and left <= 0:
                    return False
                self._cond.wait(0.2 if left is None else min(left, 0.2))

    # ------------------------------------------------------------- internal
    def _finish(self, key: str, tid: str, as_of: date, fut: Future, on_result: ResultFn | None) -> None:
        if fut.cancelled():
            res = {"error": "cancelled", "code": "CANCELLED"}
        elif fut.exception() is not None:
            res = {"error": f"FORECAST_FAILED: {fut.exception()}", "code": "FORECAST_FAILED"}
        else:
            res = fut.result()
        if on_result is not None and "error" not in res:
            try:
                on_result(key, tid, as_of, res)  # cache first, so "finished" implies "cached"
            except Exception as e:  # noqa: BLE001
                res = {"error": f"CACHE_FAILED: {e}", "code": "CACHE_FAILED"}
        with self._cond:
            if self._inflight.get(key) is not fut:
                return  # timed out earlier; the result (if ok) was still cached above
            del self._inflight[key]
            self._started.pop(key, None)
            err = res.get("error")
            if err is not None and not err.startswith(str(res.get("code"))):
                err = f"{res.get('code', 'FORECAST_FAILED')}: {err}"  # e.g. "FORECAST_FAILED: <message>"
            self._done[key] = err
            self._cond.notify_all()

    def _watch(self) -> None:
        """Per-TID timeout (TR-41): a key running longer than `timeout` is recorded as failed."""
        while not self._stop.wait(min(0.1, self.timeout / 3)):
            now = time.monotonic()
            with self._cond:
                for key, fut in list(self._inflight.items()):
                    if fut.done() or not fut.running():
                        continue
                    start = self._started.setdefault(key, now)
                    if now - start > self.timeout:
                        del self._inflight[key]
                        self._started.pop(key, None)
                        self._done[key] = f"TIMEOUT: forecast exceeded {self.timeout:g} s"
                        fut.cancel()
                        self._cond.notify_all()

    def _prune(self) -> None:
        """Drop job records older than job_ttl (TR-38) once they are done."""
        now = time.monotonic()
        for jid, job in list(self._jobs.items()):
            if now - job.created > self.job_ttl and not any(k in self._inflight for k in job.keys):
                del self._jobs[jid]
