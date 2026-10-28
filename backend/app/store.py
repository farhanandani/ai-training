"""SQLite workspace store (TR-12, TR-15, TR-16, TR-17; ARCHITECTURE section 4)."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from app.settings import Settings
from engine.ingest import read_table
from engine.schema import LOG_COLS, AtmMaster, Issue, Override

DDL = """
CREATE TABLE IF NOT EXISTS atm_master (
  tid TEXT PRIMARY KEY, location_name TEXT, location_type TEXT,
  capacity INTEGER NOT NULL, min_safe_balance INTEGER NOT NULL,
  replenish_cycle_days INTEGER NOT NULL CHECK (replenish_cycle_days BETWEEN 1 AND 31),
  denomination INTEGER NOT NULL CHECK (denomination IN (50000, 100000)),
  cost_per_visit INTEGER NOT NULL, current_fill_level INTEGER NOT NULL,
  next_visit_date TEXT, inferred INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS daily_log (
  tid TEXT NOT NULL REFERENCES atm_master(tid) ON DELETE CASCADE,
  date TEXT NOT NULL,
  opening_balance INTEGER NOT NULL, withdrawal INTEGER NOT NULL,
  replenishment INTEGER NOT NULL, closing_balance INTEGER NOT NULL,
  source TEXT NOT NULL CHECK (source IN ('dummy','upload','edit','derived')),
  PRIMARY KEY (tid, date)
);
CREATE TABLE IF NOT EXISTS holidays (date TEXT PRIMARY KEY, name TEXT NOT NULL,
  type TEXT NOT NULL CHECK (type IN ('new_year','christmas','idul_fitri','cuti_bersama','national')));
CREATE TABLE IF NOT EXISTS true_demand (tid TEXT NOT NULL, date TEXT NOT NULL, true_demand INTEGER NOT NULL,
  PRIMARY KEY (tid, date));
CREATE TABLE IF NOT EXISTS overrides (tid TEXT NOT NULL REFERENCES atm_master(tid) ON DELETE CASCADE,
  visit_date TEXT NOT NULL, amount INTEGER, skipped INTEGER NOT NULL DEFAULT 0,
  moved_from TEXT, PRIMARY KEY (tid, visit_date));
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS forecast_cache (cache_key TEXT PRIMARY KEY, tid TEXT NOT NULL, as_of TEXT NOT NULL,
  created_at TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS validation_issues (id INTEGER PRIMARY KEY, kind TEXT, severity TEXT, code TEXT,
  tid TEXT, date TEXT, message TEXT);
CREATE TABLE IF NOT EXISTS dataset_meta (id INTEGER PRIMARY KEY CHECK (id = 1), dataset_version INTEGER NOT NULL,
  source_label TEXT NOT NULL);
"""

LOG_ALL = [*LOG_COLS, "source"]
_INT_COLS = ["opening_balance", "withdrawal", "replenishment", "closing_balance"]
_MASTER_COLS = [
    "tid",
    "location_name",
    "location_type",
    "capacity",
    "min_safe_balance",
    "replenish_cycle_days",
    "denomination",
    "cost_per_visit",
    "current_fill_level",
    "next_visit_date",
    "inferred",
]


def _iso(d) -> str | None:
    if d is None:
        return None
    if isinstance(d, str):
        return d
    if isinstance(d, datetime):
        return d.date().isoformat()
    if isinstance(d, date):
        return d.isoformat()
    return None if pd.isna(d) else pd.Timestamp(d).date().isoformat()


def _date(s: str | None) -> date | None:
    return None if s is None else date.fromisoformat(s)


class Store:
    def __init__(self, path: Path, seed_dir: Path):
        self.path = Path(path)
        self.seed_dir = Path(seed_dir)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._depth = 0
        # autocommit mode; transactions are explicit in _tx
        self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(DDL)
        with self._tx() as c:
            for k, v in Settings().business_defaults.items():
                c.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (k, json.dumps(v)))
        if self._q("SELECT COUNT(*) FROM dataset_meta")[0][0] == 0:
            self.seed_from_dummy()
        self.cache_prune()  # TR-17

    # ---------------------------------------------------------------- infra
    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @contextmanager
    def _tx(self):
        """Single write transaction; re-entrant (inner calls join the outer one)."""
        with self._lock:
            if self._depth:
                yield self._conn
                return
            self._conn.execute("BEGIN IMMEDIATE")
            self._depth = 1
            try:
                yield self._conn
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            else:
                self._conn.execute("COMMIT")
            finally:
                self._depth = 0

    def transaction(self):
        """Public handle on _tx: callers group several writes into one SQLite transaction (TR-12)."""
        return self._tx()

    def _q(self, sql: str, params=()) -> list[tuple]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def _bump(self) -> None:
        self._conn.execute("UPDATE dataset_meta SET dataset_version = dataset_version + 1 WHERE id = 1")

    # ----------------------------------------------------------------- seed
    def seed_from_dummy(self) -> None:
        def load(name: str, kind: str) -> pd.DataFrame:
            df, _ = read_table((self.seed_dir / name).read_bytes(), name, kind)
            return df

        log = load("atm_daily_log.csv", "log")
        master = load("atm_master.csv", "master")
        hol = load("holidays_id.csv", "holidays")
        # not a read_table kind (TR-16): plain pandas
        td = pd.read_csv(self.seed_dir / "atm_true_demand.csv")
        with self._tx() as c:
            for t in ("daily_log", "true_demand", "overrides", "forecast_cache", "validation_issues"):
                c.execute(f"DELETE FROM {t}")
            c.execute("DELETE FROM holidays")
            c.execute("DELETE FROM atm_master")
            self._insert_master(_master_rows(master))
            self._insert_log(log.assign(source="dummy"), "dummy")
            self._insert_holidays(hol)
            c.executemany(
                "INSERT INTO true_demand(tid, date, true_demand) VALUES (?,?,?)",
                [(t, _iso(d), int(v)) for t, d, v in zip(td["tid"], td["date"], td["true_demand"])],
            )
            c.execute(
                "INSERT INTO dataset_meta(id, dataset_version, source_label) VALUES (1, 1, 'Dummy data') "
                "ON CONFLICT(id) DO UPDATE SET dataset_version = dataset_version + 1, "
                "source_label = 'Dummy data'"
            )

    # ------------------------------------------------------------------ log
    def _insert_log(self, df: pd.DataFrame, source: str) -> None:
        if len(df) == 0:
            return
        src = [source] * len(df)
        if "source" in df.columns:  # keep 'derived' provenance, otherwise use the caller's label
            src = [s if s == "derived" else source for s in df["source"]]
        rows = [
            (t, _iso(d), int(o), int(w), int(r), int(cl), s)
            for t, d, o, w, r, cl, s in zip(
                df["tid"],
                df["date"],
                df["opening_balance"],
                df["withdrawal"],
                df["replenishment"],
                df["closing_balance"],
                src,
            )
        ]
        self._conn.executemany(
            "INSERT INTO daily_log(tid, date, opening_balance, withdrawal, replenishment, closing_balance, "
            "source) VALUES (?,?,?,?,?,?,?) ON CONFLICT(tid, date) DO UPDATE SET "
            "opening_balance=excluded.opening_balance, withdrawal=excluded.withdrawal, "
            "replenishment=excluded.replenishment, closing_balance=excluded.closing_balance, "
            "source=excluded.source",
            rows,
        )

    def get_log(self, tids: list[str] | None = None, start=None, end=None) -> pd.DataFrame:
        where, params = [], []
        if tids is not None:
            if not tids:
                return _log_frame([])
            where.append(f"tid IN ({','.join('?' * len(tids))})")
            params += list(tids)
        if start is not None:
            where.append("date >= ?")
            params.append(_iso(start))
        if end is not None:
            where.append("date <= ?")
            params.append(_iso(end))
        sql = f"SELECT {', '.join(LOG_ALL)} FROM daily_log"
        if where:
            sql += " WHERE " + " AND ".join(where)
        return _log_frame(self._q(sql + " ORDER BY tid, date", tuple(params)))

    def upsert_log(self, df: pd.DataFrame, source: str) -> None:
        with self._tx():
            self._insert_log(df, source)
            self._bump()

    def replace_log(self, df: pd.DataFrame) -> None:
        """TR-12: replace the log; drop master rows (and, by cascade, overrides) of absent TIDs."""
        tids = sorted(set(df["tid"]))
        with self._tx() as c:
            c.execute("DELETE FROM daily_log")
            c.execute("DELETE FROM true_demand")  # TR-16
            if tids:
                c.execute(f"DELETE FROM atm_master WHERE tid NOT IN ({','.join('?' * len(tids))})", tids)
            else:
                c.execute("DELETE FROM atm_master")
            self._insert_log(df, "upload")
            self._bump()

    def clear_true_demand(self) -> None:
        """TR-16: once client data is merged in, the dummy ground truth no longer describes the log."""
        with self._tx() as c:
            c.execute("DELETE FROM true_demand")

    def delete_log(self, keys: list[tuple[str, date]]) -> None:
        with self._tx() as c:
            c.executemany("DELETE FROM daily_log WHERE tid = ? AND date = ?", [(t, _iso(d)) for t, d in keys])
            self._bump()

    # --------------------------------------------------------------- master
    def _insert_master(self, rows: list[AtmMaster]) -> None:
        upd = ", ".join(f"{c}=excluded.{c}" for c in _MASTER_COLS[1:])
        # upsert, not REPLACE: REPLACE would cascade-delete the TID's log rows
        self._conn.executemany(
            f"INSERT INTO atm_master({', '.join(_MASTER_COLS)}) VALUES ({','.join('?' * len(_MASTER_COLS))}) "
            f"ON CONFLICT(tid) DO UPDATE SET {upd}",
            [
                (
                    m.tid,
                    m.location_name,
                    m.location_type,
                    int(m.capacity),
                    int(m.min_safe_balance),
                    int(m.replenish_cycle_days),
                    int(m.denomination),
                    int(m.cost_per_visit),
                    int(m.current_fill_level),
                    _iso(m.next_visit_date),
                    int(bool(m.inferred)),
                )
                for m in rows
            ],
        )

    def get_master(self) -> list[AtmMaster]:
        rows = self._q(f"SELECT {', '.join(_MASTER_COLS)} FROM atm_master ORDER BY tid")
        return [AtmMaster(*r[:9], next_visit_date=_date(r[9]), inferred=bool(r[10])) for r in rows]

    def put_master(self, rows: list[AtmMaster], replace: bool = False) -> None:
        with self._tx() as c:
            if replace:
                tids = [m.tid for m in rows]
                if tids:
                    c.execute(f"DELETE FROM atm_master WHERE tid NOT IN ({','.join('?' * len(tids))})", tids)
                else:
                    c.execute("DELETE FROM atm_master")
            self._insert_master(rows)
            self._bump()

    # ------------------------------------------------------------- holidays
    def _insert_holidays(self, df: pd.DataFrame) -> None:
        self._conn.executemany(
            "INSERT INTO holidays(date, name, type) VALUES (?,?,?) "
            "ON CONFLICT(date) DO UPDATE SET name=excluded.name, type=excluded.type",
            [(_iso(d), n, t) for d, n, t in zip(df["date"], df["name"], df["type"])],
        )

    def get_holidays(self) -> pd.DataFrame:
        rows = self._q("SELECT date, name, type FROM holidays ORDER BY date")
        return pd.DataFrame(
            {
                "date": [_date(r[0]) for r in rows],
                "name": [r[1] for r in rows],
                "type": [r[2] for r in rows],
            }
        )

    def put_holidays(self, df: pd.DataFrame, replace: bool = False) -> None:
        """Merge by date; `replace=True` (TR-12 replace mode) empties the table first."""
        with self._tx() as c:
            if replace:
                c.execute("DELETE FROM holidays")
            self._insert_holidays(df)
            self._bump()

    # ----------------------------------------------------------- true demand
    def get_true_demand(self) -> pd.DataFrame | None:
        rows = self._q("SELECT tid, date, true_demand FROM true_demand ORDER BY tid, date")
        if not rows:
            return None
        return pd.DataFrame(
            {
                "tid": [r[0] for r in rows],
                "date": [_date(r[1]) for r in rows],
                "true_demand": pd.Series([r[2] for r in rows], dtype="int64"),
            }
        )

    # ------------------------------------------------------------ overrides
    def get_overrides(self) -> list[Override]:
        rows = self._q(
            "SELECT tid, visit_date, amount, skipped, moved_from FROM overrides ORDER BY tid, visit_date"
        )
        return [Override(r[0], _date(r[1]), r[2], bool(r[3]), _date(r[4])) for r in rows]

    def put_overrides(self, items: list[Override]) -> None:
        with self._tx() as c:
            c.executemany(
                "INSERT INTO overrides(tid, visit_date, amount, skipped, moved_from) VALUES (?,?,?,?,?) "
                "ON CONFLICT(tid, visit_date) DO UPDATE SET amount=excluded.amount, "
                "skipped=excluded.skipped, moved_from=excluded.moved_from",
                [
                    (
                        o.tid,
                        _iso(o.visit_date),
                        None if o.amount is None else int(o.amount),
                        int(bool(o.skipped)),
                        _iso(o.moved_from),
                    )
                    for o in items
                ],
            )
            self._bump()

    def clear_overrides(self) -> None:
        with self._tx() as c:
            c.execute("DELETE FROM overrides")
            self._bump()

    # ------------------------------------------------------------- settings
    def get_setting(self, key: str):
        rows = self._q("SELECT value FROM settings WHERE key = ?", (key,))
        return json.loads(rows[0][0]) if rows else None

    def set_setting(self, key: str, value) -> None:
        with self._tx() as c:
            c.execute(
                "INSERT INTO settings(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, json.dumps(value)),
            )

    # ---------------------------------------------------------------- cache
    def cache_get(self, key: str) -> dict | None:
        rows = self._q("SELECT payload FROM forecast_cache WHERE cache_key = ?", (key,))
        return json.loads(rows[0][0]) if rows else None

    def cache_put(self, key: str, tid: str, as_of, payload: dict) -> None:
        with self._tx() as c:
            c.execute(
                "INSERT OR REPLACE INTO forecast_cache(cache_key, tid, as_of, created_at, payload) "
                "VALUES (?,?,?,?,?)",
                (
                    key,
                    tid,
                    _iso(as_of),
                    datetime.now().isoformat(timespec="microseconds"),
                    json.dumps(payload),
                ),
            )

    def cache_latest(self, tid: str, as_of) -> dict | None:
        """Newest cached payload for (tid, as_of), whatever its data hash (incremental refit, AC5)."""
        rows = self._q(
            "SELECT payload FROM forecast_cache WHERE tid = ? AND as_of = ? "
            "ORDER BY created_at DESC, rowid DESC LIMIT 1",
            (tid, _iso(as_of)),
        )
        return json.loads(rows[0][0]) if rows else None

    def clear_forecast_cache(self) -> None:
        with self._tx() as c:
            c.execute("DELETE FROM forecast_cache")

    def cache_prune(self, keep: int = 500) -> None:
        with self._tx() as c:
            c.execute(
                "DELETE FROM forecast_cache WHERE cache_key NOT IN ("
                "SELECT cache_key FROM forecast_cache ORDER BY created_at DESC, rowid DESC LIMIT ?)",
                (keep,),
            )

    # --------------------------------------------------------------- issues
    def save_issues(self, kind: str, issues: list[Issue]) -> None:
        """Replace the stored issues of this kind (TR-14)."""
        with self._tx() as c:
            c.execute("DELETE FROM validation_issues WHERE kind = ?", (kind,))
            c.executemany(
                "INSERT INTO validation_issues(kind, severity, code, tid, date, message) VALUES (?,?,?,?,?,?)",
                [(kind, i.severity, i.code, i.tid, _iso(i.date), i.message) for i in issues],
            )

    def get_issues(self) -> list[Issue]:
        rows = self._q("SELECT severity, code, message, tid, date FROM validation_issues ORDER BY id")
        return [Issue(r[0], r[1], r[2], r[3], _date(r[4])) for r in rows]

    # ----------------------------------------------------------------- meta
    def dataset_version(self) -> int:
        return self._q("SELECT dataset_version FROM dataset_meta WHERE id = 1")[0][0]

    def bump_version(self) -> int:
        with self._tx():
            self._bump()
            return self.dataset_version()

    def source_label(self) -> str:
        return self._q("SELECT source_label FROM dataset_meta WHERE id = 1")[0][0]

    def set_source_label(self, label: str) -> None:
        with self._tx() as c:
            c.execute("UPDATE dataset_meta SET source_label = ? WHERE id = 1", (label,))

    # --------------------------------------------------------------- hashes
    def tid_hash(self, tid: str, as_of) -> str:
        """sha256 over the canonical CSV of this TID's rows with date <= as_of (source excluded)."""
        df = self.get_log([tid], end=as_of)[LOG_COLS]
        # return hashlib.sha256(df.to_csv(index=False, lineterminator="\n").encode()).hexdigest()
        return frame_hash(df)

    def holiday_hash(self) -> str:
        df = self.get_holidays()
        # return hashlib.sha256(df.to_csv(index=False, lineterminator="\n").encode()).hexdigest()
        return frame_hash(df)


def frame_hash(df: pd.DataFrame) -> str:
    """sha256 over a frame's canonical CSV. tid_hash = frame_hash(log rows <= as_of, LOG_COLS);
    holiday_hash = frame_hash(get_holidays()). Callers that already hold those frames hash them directly."""
    return hashlib.sha256(df.to_csv(index=False, lineterminator="\n").encode()).hexdigest()


def _log_frame(rows: list[tuple]) -> pd.DataFrame:
    data = {
        "tid": [r[0] for r in rows],
        "date": [_date(r[1]) for r in rows],
        **{c: pd.Series([r[i] for r in rows], dtype="int64") for i, c in enumerate(_INT_COLS, start=2)},
        "source": [r[6] for r in rows],
    }
    return pd.DataFrame(data, columns=LOG_ALL)


def _master_rows(df: pd.DataFrame) -> list[AtmMaster]:
    rows = []
    for r in df.to_dict("records"):
        nv = r.get("next_visit_date")
        r["next_visit_date"] = None if nv is None or pd.isna(nv) else nv
        rows.append(AtmMaster(**{k: r[k] for k in AtmMaster.__dataclass_fields__ if k in r}))
    return rows
