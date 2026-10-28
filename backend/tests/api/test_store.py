from datetime import date

import pandas as pd

from engine.schema import AtmMaster, Issue, Override


def _edit(store, tid: str, d: date, delta: int = 1_000_000) -> None:
    df = store.get_log([tid], d, d).copy()
    df["withdrawal"] += delta
    df["closing_balance"] -= delta
    store.upsert_log(df, "edit")


def test_seed_counts(store):
    assert len(store.get_log()) == 7300
    assert len(store.get_master()) == 10
    assert len(store.get_holidays()) == 45
    assert len(store.get_true_demand()) == 7300
    assert store.dataset_version() == 1
    assert store.source_label() == "Dummy data"


def test_get_log_convention(store):
    df = store.get_log(["TID-JKT-0001"], date(2026, 1, 1), date(2026, 1, 5))
    assert list(df.columns) == [
        "tid",
        "date",
        "opening_balance",
        "withdrawal",
        "replenishment",
        "closing_balance",
        "source",
    ]
    assert len(df) == 5
    assert isinstance(df["date"].iloc[0], date)
    assert str(df["withdrawal"].dtype) == "int64"
    assert set(df["source"]) == {"dummy"}


def test_get_true_demand_none_when_empty(store):
    store.replace_log(store.get_log())
    assert store.get_true_demand() is None


def test_upsert_bumps_version_and_changes_only_tid_hash(store):
    h_after = store.tid_hash("TID-JKT-0001", date(2026, 3, 6))
    h_before = store.tid_hash("TID-JKT-0001", date(2026, 1, 31))
    h_other = store.tid_hash("TID-JKT-0002", date(2026, 3, 6))
    v = store.dataset_version()
    _edit(store, "TID-JKT-0001", date(2026, 2, 1))
    assert store.dataset_version() == v + 1
    assert store.tid_hash("TID-JKT-0001", date(2026, 3, 6)) != h_after
    assert store.tid_hash("TID-JKT-0001", date(2026, 1, 31)) == h_before
    assert store.tid_hash("TID-JKT-0002", date(2026, 3, 6)) == h_other
    assert store.get_log(["TID-JKT-0001"], date(2026, 2, 1), date(2026, 2, 1))["source"].iloc[0] == "edit"


def test_hash_ignores_source(store):
    h = store.tid_hash("TID-JKT-0001", date(2026, 3, 6))
    df = store.get_log(["TID-JKT-0001"])
    store.upsert_log(df, "upload")
    assert store.tid_hash("TID-JKT-0001", date(2026, 3, 6)) == h


def test_holiday_hash_changes_on_put(store):
    h = store.holiday_hash()
    store.put_holidays(pd.DataFrame([{"date": date(2030, 1, 1), "name": "NY", "type": "new_year"}]))
    assert store.holiday_hash() != h
    assert len(store.get_holidays()) == 46


def test_replace_log_cascades_and_clears_true_demand(store):
    store.put_overrides([Override("TID-JKT-0001", date(2026, 3, 10), 5_000_000)])
    store.put_overrides([Override("TID-JKT-0002", date(2026, 3, 11), None, skipped=True)])
    keep = store.get_log(["TID-JKT-0001"])
    v = store.dataset_version()
    store.replace_log(keep)
    assert set(store.get_log()["tid"]) == {"TID-JKT-0001"}
    assert [m.tid for m in store.get_master()] == ["TID-JKT-0001"]
    assert [o.tid for o in store.get_overrides()] == ["TID-JKT-0001"]
    assert store.get_true_demand() is None
    assert store.dataset_version() == v + 1


def test_delete_log(store):
    store.delete_log([("TID-JKT-0001", date(2026, 1, 1)), ("TID-JKT-0001", date(2026, 1, 2))])
    assert len(store.get_log()) == 7298


def test_master_roundtrip_and_replace(store):
    m = store.get_master()[0]
    m.capacity += 50_000_000
    store.put_master([m])
    assert len(store.get_master()) == 10
    assert store.get_master()[0].capacity == m.capacity
    assert len(store.get_log()) == 7300  # upsert must not cascade-delete the log
    extra = AtmMaster("TID-NEW-0001", "X", "mall", 1, 1, 3, 100000, 1, 1, date(2026, 5, 1), True)
    store.put_master([extra], replace=True)
    assert [x.tid for x in store.get_master()] == ["TID-NEW-0001"]
    assert store.get_master()[0].next_visit_date == date(2026, 5, 1)
    assert store.get_master()[0].inferred is True
    assert len(store.get_log()) == 0


def test_overrides_and_settings_and_issues(store):
    o = Override("TID-JKT-0001", date(2026, 3, 10), None, True, date(2026, 3, 9))
    store.put_overrides([o])
    assert store.get_overrides() == [o]
    store.clear_overrides()
    assert store.get_overrides() == []
    assert store.get_setting("h") == 14
    store.set_setting("budget", {"a": [1, 2]})
    assert store.get_setting("budget") == {"a": [1, 2]}
    assert store.get_setting("nope") is None
    store.save_issues("log", [Issue("warning", "CONTINUITY", "m", "TID-JKT-0001", date(2026, 1, 2))])
    store.save_issues("master", [Issue("info", "UNKNOWN_COLUMN", "c")])
    store.save_issues("log", [])
    assert [i.code for i in store.get_issues()] == ["UNKNOWN_COLUMN"]


def test_cache_roundtrip_and_prune(store):
    assert store.cache_get("k0") is None
    for i in range(520):
        store.cache_put(f"k{i}", "TID-JKT-0001", date(2026, 3, 1), {"i": i})
    assert store.cache_get("k5") == {"i": 5}
    store.cache_put("k5", "TID-JKT-0001", date(2026, 3, 1), {"i": "new"})  # overwrite
    store.cache_prune()
    assert store.cache_get("k0") is None and store.cache_get("k20") is None  # 20 oldest; refreshed k5 spared
    assert store.cache_get("k21") == {"i": 21}
    assert store.cache_get("k5") == {"i": "new"}  # refreshed entry is newest
    assert store.cache_get("k519") == {"i": 519}
    store.cache_prune(keep=10)
    assert store.cache_get("k5") == {"i": "new"} and store.cache_get("k21") is None


def test_reset_restores_dummy(store):
    store.put_overrides([Override("TID-JKT-0001", date(2026, 3, 10), 5_000_000)])
    store.cache_put("k", "TID-JKT-0001", date(2026, 3, 1), {"x": 1})
    store.replace_log(store.get_log(["TID-JKT-0001"]))
    store.set_source_label("My upload")
    v = store.dataset_version()
    store.seed_from_dummy()
    assert len(store.get_log()) == 7300 and len(store.get_master()) == 10
    assert len(store.get_true_demand()) == 7300
    assert store.get_overrides() == [] and store.cache_get("k") is None
    assert store.source_label() == "Dummy data"
    assert store.dataset_version() == v + 1


def test_reopen_does_not_reseed(tmp_path, seed_dir):
    from app.store import Store

    s = Store(tmp_path / "w.db", seed_dir)
    s.set_source_label("X")
    s.close()
    s2 = Store(tmp_path / "w.db", seed_dir)
    assert s2.source_label() == "X" and s2.dataset_version() == 1
    s2.close()


def test_settings_defaults(monkeypatch):
    from app.settings import Settings

    monkeypatch.setenv("CASHFC_PORT", "9000")
    monkeypatch.setenv("CASHFC_WARMUP_SCENARIOS", "false")
    s = Settings()
    assert s.port == 9000 and s.host == "127.0.0.1" and s.warmup_scenarios is False
    assert s.max_upload_mb == 20 and s.workers >= 1
    assert s.workspace_db.is_absolute() and s.seed_dir.name == "data"
    assert s.business_defaults == {
        "h": 14,
        "sl": "p90",
        "budget": None,
        "overstock_frac": 0.30,
        "idle_rate": 0.06,
        "detect_jump_frac": 0.20,
    }
