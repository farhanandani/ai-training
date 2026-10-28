"""Data writes (ARCHITECTURE 8, TR-12..TR-14, TR-37): uploads, row edits, master/holiday edits, reset.

Every write: parse/validate -> infer + put master rows for unknown TIDs -> store write (one transaction)
-> validate the log and save the issues -> (version already bumped by the store) -> ensure_forecasts at the
current as_of -> TR-37 body."""

from __future__ import annotations

import io
import threading
from datetime import date

import pandas as pd

from app.errors import ApiError
from app.services import Services
from app.store import _master_rows
from engine.ingest import MASTER_COLS, UnreadableFile, read_table
from engine.preprocess import MIN_TRAIN_DAYS, allowed_as_of_range
from engine.schema import LOG_COLS, AtmMaster, Issue
from engine.validate import infer_master, validate_log

HOLIDAY_TYPES = ("new_year", "christmas", "idul_fitri", "cuti_bersama", "national")
DENOMINATIONS = (50_000, 100_000)
DUMMY_LABEL = "Dummy data"
DOWNLOAD_NAMES = {"log": "atm_daily_log.csv", "master": "atm_master.csv", "holidays": "holidays_id.csv"}


def issue_dict(i: Issue) -> dict:
    return {
        "severity": i.severity,
        "code": i.code,
        "message": i.message,
        "tid": i.tid,
        "date": i.date.isoformat() if i.date is not None else None,
    }


def validate_all(log: pd.DataFrame, masters: list[AtmMaster], as_of: date | None) -> list[Issue]:
    """validate_log against the reviewed master rows (inferred rows keep their UNKNOWN_TID warning until
    edited), plus SHORT_HISTORY (TR-13) per TID at the current as_of."""
    issues = validate_log(log, [m for m in masters if not m.inferred])
    if as_of is None or log.empty:
        return issues
    for tid, first in log.groupby("tid", sort=True)["date"].min().items():
        days = (as_of - first).days + 1
        if days < MIN_TRAIN_DAYS:
            issues.append(
                Issue(
                    "warning",
                    "SHORT_HISTORY",
                    f"{tid} has {max(days, 0)} days of history before {as_of.isoformat()} "
                    f"(needs {MIN_TRAIN_DAYS}); shown as insufficient history",
                    str(tid),
                )
            )
    return issues


def _recompute_as_of(svc: Services, log: pd.DataFrame) -> date | None:
    """services.current_as_of() (controller ruling); None when the data no longer covers it."""
    if log.empty:
        return None
    as_of = svc.current_as_of()
    lo, hi = allowed_as_of_range(log)
    return as_of if lo <= as_of <= hi else None


def finish_write(
    svc: Services, tids: set[str] | None = None, parse_issues: list[Issue] | None = None
) -> dict:
    """Validate + store issues, start the recompute, build the TR-37 body.
    `tids`: row edits report only those TIDs' issues; `parse_issues`: an upload's file issues."""
    store = svc.store
    log = store.get_log()
    as_of = _recompute_as_of(svc, log)
    issues = validate_all(log, store.get_master(), as_of)
    store.save_issues("log", issues)  # TR-14
    if parse_issues is not None:
        store.save_issues("upload", parse_issues)
    shown = issues if tids is None else [i for i in issues if i.tid in tids]
    pending, job_id = [], None
    if as_of is not None:
        _, pending, job_id = svc.ensure_forecasts(as_of)
    return {
        "dataset_version": store.dataset_version(),
        "issues": [issue_dict(i) for i in [*(parse_issues or []), *shown]],
        "job": {"job_id": job_id, "pending_tids": pending},
    }


def _infer_unknown(log: pd.DataFrame, masters: list[AtmMaster]) -> list[AtmMaster]:
    known = {m.tid for m in masters}
    return [infer_master(log, t, masters) for t in sorted(set(log["tid"]) - known)]


# --------------------------------------------------------------------- upload
def upload(svc: Services, data: bytes, filename: str, kind: str, mode: str) -> dict:
    store = svc.store
    masters = store.get_master()
    try:
        df, issues = read_table(
            data,
            filename,
            kind,
            detect_jump_frac=float(svc._biz("detect_jump_frac")),
            capacities={m.tid: int(m.capacity) for m in masters},
        )
    except UnreadableFile as e:  # nothing is written (TR-12)
        raise ApiError(422, e.issues[0].code, str(e), {"issues": [issue_dict(i) for i in e.issues]}) from e
    replace = mode == "replace"
    if kind == "log":
        _upload_log(svc, df, filename, replace)
    elif kind == "master":
        rows = _valid_master(_master_rows(df), issues)
        # if rows or not replace:  # an empty replace would cascade-delete the whole log
        if rows:  # no valid row: nothing written, no version bump (an empty replace would wipe the log)
            # store.put_master(rows, replace=replace)
            kept = store.put_master(rows, replace=replace)
            if kept:  # F5: TIDs absent from the file but with log rows stay (their log is not deleted)
                issues.append(
                    Issue(
                        "warning",
                        "MASTER_KEPT_HAS_LOG",
                        f"{len(kept)} ATM{'s' if len(kept) != 1 else ''} not in the file still have daily log "
                        f"data and were kept: {', '.join(kept)} (delete their log rows to remove them)",
                    )
                )
    else:
        df = _valid_holidays(df, issues)
        # if len(df) or not replace:
        if len(df):
            store.put_holidays(df, replace=replace)
    return finish_write(svc, parse_issues=issues)


def _upload_log(svc: Services, df: pd.DataFrame, filename: str, replace: bool) -> None:
    store = svc.store
    # if replace and df.empty:
    if df.empty:  # merge too: no valid row changes neither the label nor the true demand
        return  # every row was rejected: keep the current data, the issues say why
    masters = store.get_master()
    with store.transaction():
        new = _infer_unknown(df, masters)
        if new:
            store.put_master(new)  # upsert_log/replace_log need the master rows first
        if replace:
            store.replace_log(df)
            store.clear_forecast_cache()  # a new dataset gets full runs, never incremental refits
            store.set_source_label(filename)
        else:
            store.upsert_log(df, "upload")
            store.clear_true_demand()  # TR-16
            if store.source_label() == DUMMY_LABEL:
                store.set_source_label(f"{DUMMY_LABEL} + {filename}")


def _valid_master(rows: list[AtmMaster], issues: list[Issue]) -> list[AtmMaster]:
    """Rows the atm_master CHECK constraints would reject become row-level issues, never a 500."""
    out = []
    for m in rows:
        if m.denomination not in DENOMINATIONS:
            issues.append(Issue("error", "BAD_VALUE", "denomination must be 50000 or 100000", m.tid))
        elif not 1 <= m.replenish_cycle_days <= 31:
            issues.append(Issue("error", "BAD_VALUE", "replenish_cycle_days must be 1-31", m.tid))
        else:
            out.append(m)
    return out


def _valid_holidays(df: pd.DataFrame, issues: list[Issue]) -> pd.DataFrame:
    ok = df["type"].isin(HOLIDAY_TYPES)
    for d, t in zip(df.loc[~ok, "date"], df.loc[~ok, "type"], strict=True):
        issues.append(
            Issue(
                "error", "BAD_VALUE", f"holiday type {t!r} must be one of {', '.join(HOLIDAY_TYPES)}", None, d
            )
        )
    return df[ok]


# ------------------------------------------------------------------ row edits
def patch_log(svc: Services, rows: list[dict]) -> dict:
    """TR-37 partial update: given fields replace the stored ones, the source becomes 'edit'."""
    store = svc.store
    known = {m.tid for m in store.get_master()}
    out = []
    for r in rows:
        if r["tid"] not in known:
            raise ApiError(404, "UNKNOWN_TID", f"unknown TID {r['tid']}", {"tid": r["tid"]})
        cur = store.get_log([r["tid"]], r["date"], r["date"])
        if cur.empty:
            d = r["date"].isoformat()
            raise ApiError(
                404, "UNKNOWN_ROW", f"no log row for {r['tid']} on {d}", {"tid": r["tid"], "date": d}
            )
        rec = cur[LOG_COLS].iloc[0].to_dict()
        rec.update({k: v for k, v in r.items() if v is not None})
        out.append(rec)
    store.upsert_log(pd.DataFrame(out, columns=LOG_COLS), "edit")
    return finish_write(svc, tids={r["tid"] for r in rows})


def post_log(svc: Services, rows: list[dict]) -> dict:
    store = svc.store
    df = pd.DataFrame(rows, columns=LOG_COLS)
    with store.transaction():
        new = _infer_unknown(df, store.get_master())
        if new:
            store.put_master(new)
        store.upsert_log(df, "edit")
    return finish_write(svc, tids=set(df["tid"]))


def delete_log(svc: Services, keys: list[tuple[str, date]]) -> dict:
    svc.store.delete_log(keys)
    return finish_write(svc, tids={t for t, _ in keys})


# ------------------------------------------------------------ master/holidays
def put_master(svc: Services, rows: list[AtmMaster]) -> dict:
    svc.store.put_master(rows)  # upsert by tid; a full replace would cascade-delete log rows
    return finish_write(svc)


def put_holidays(svc: Services, df: pd.DataFrame) -> dict:
    svc.store.put_holidays(df, replace=True)  # PUT = the whole calendar (rows can be removed)
    return finish_write(svc)


def reset(svc: Services) -> dict:
    svc.store.seed_from_dummy()  # also clears overrides, forecast cache and stored issues
    # return finish_write(svc)
    out = finish_write(svc)
    if svc.warm_on_reset:  # the cache was cleared: pre-compute every demo scenario again (like startup)
        threading.Thread(target=svc.warmup, daemon=True, name="warmup-reset").start()
    return out


# ------------------------------------------------------------------- download
def download_csv(svc: Services, kind: str) -> str:
    store = svc.store
    if kind == "log":
        df = store.get_log()[LOG_COLS]
    elif kind == "master":
        df = pd.DataFrame(
            [{c: getattr(m, c) for c in MASTER_COLS} for m in store.get_master()], columns=MASTER_COLS
        )
    else:
        df = store.get_holidays()
    buf = io.StringIO()
    df.to_csv(buf, index=False, lineterminator="\n")
    return buf.getvalue()
