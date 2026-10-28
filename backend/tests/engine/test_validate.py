from datetime import date

from engine.validate import infer_master, validate_log


def test_dummy_log_has_no_identity_errors(log_df, master_list):
    issues = validate_log(log_df, master_list)
    assert not [i for i in issues if i.code == "BALANCE_IDENTITY"]


def test_identity_and_continuity_warnings(log_df, master_list):
    df = log_df.copy()
    tid, d = "TID-JKT-0001", date(2026, 2, 10)
    m = (df["tid"] == tid) & (df["date"] == d)
    df.loc[m, "closing_balance"] += 1_000_000
    issues = validate_log(df, master_list)
    ident = [i for i in issues if i.code == "BALANCE_IDENTITY" and i.tid == tid]
    cont = [i for i in issues if i.code == "CONTINUITY" and i.tid == tid]
    assert [i.date for i in ident] == [d]
    # continuity is reported on the day whose opening no longer matches the prior closing
    assert [i.date for i in cont] == [date(2026, 2, 11)]


def test_missing_dates_reported_as_range(log_df, master_list):
    tid = "TID-JKT-0001"
    drop = (
        (log_df["tid"] == tid) & (log_df["date"] >= date(2026, 1, 5)) & (log_df["date"] <= date(2026, 1, 7))
    )
    issues = validate_log(log_df[~drop], master_list)
    miss = [i for i in issues if i.code == "MISSING_DATES"]
    assert len(miss) == 1
    assert "2026-01-05" in miss[0].message and "2026-01-07" in miss[0].message


def test_unknown_tid_flagged(log_df, master_list):
    issues = validate_log(log_df, master_list[1:])
    assert [i.tid for i in issues if i.code == "UNKNOWN_TID"] == [master_list[0].tid]


def test_infer_master_for_new_tid(log_df, master_list):
    df = log_df.copy()
    df.loc[df["tid"] == "TID-JKT-0001", "tid"] = "TID-NEW-1"
    m = infer_master(df, "TID-NEW-1", master_list)
    g = df[df["tid"] == "TID-NEW-1"]
    assert m.capacity % 50_000_000 == 0
    assert m.capacity >= max(g["opening_balance"].max(), g["closing_balance"].max())
    assert m.replenish_cycle_days == 4
    assert m.inferred is True
    assert m.denomination == 100_000
