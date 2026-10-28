import io
from datetime import date

import pandas as pd
import pytest
from openpyxl import Workbook

from engine.ingest import UnreadableFile, read_table
from engine.schema import LOG_COLS

HDR = "tid,date,opening_balance,withdrawal,replenishment,closing_balance"
ROWS = [
    "A,2026-03-01,1000,100,0,900",
    "A,2026-03-02,900,100,0,800",
    "A,2026-03-03,800,100,0,700",
]


def csv_bytes(rows, hdr=HDR, sep=","):
    lines = [hdr, *rows]
    return "\n".join(lines).replace(",", sep).encode()


def log(rows, **kw):
    return read_table(csv_bytes(rows), "x.csv", "log", **kw)


def codes(issues):
    return [i.code for i in issues]


def test_csv_comma_and_semicolon_detected():
    a, _ = read_table(csv_bytes(ROWS), "a.csv", "log")
    b, _ = read_table(csv_bytes(ROWS, sep=";"), "b.csv", "log")
    pd.testing.assert_frame_equal(a, b)
    assert len(a) == 3


def test_alias_headers():
    hdr = "Terminal ID;Tanggal;Saldo Awal;Penarikan;Isi Ulang;Saldo Akhir"
    df, _ = read_table(csv_bytes(ROWS, hdr=hdr, sep=";"), "a.csv", "log")
    assert list(df.columns) == [*LOG_COLS, "source"]
    assert (df["source"] == "upload").all()


def test_date_formats():
    rows = [
        "A,2026-03-01,1,0,0,1",
        "B,01/03/2026,1,0,0,1",
        "C,01-03-2026,1,0,0,1",
        "D,2026/03/01,1,0,0,1",
    ]
    df, issues = log(rows)
    assert set(df["date"]) == {date(2026, 3, 1)}
    assert list(df["tid"]) == ["A", "B", "C"]
    assert codes(issues) == ["BAD_DATE"]


def test_rp_prefix_and_decimal():
    df, issues = log(["A,2026-03-01,Rp 1500000,0,0,1500000.6"])
    assert df.iloc[0]["opening_balance"] == 1500000
    assert df.iloc[0]["closing_balance"] == 1500001
    assert issues == []


def test_id_thousand_separator_is_row_error():
    df, issues = log(["A,2026-03-01,1.000.000,0,0,5", "A,2026-03-02,5,0,0,5"])
    assert len(df) == 1
    bad = [i for i in issues if i.code == "BAD_AMOUNT"]
    assert len(bad) == 1 and bad[0].severity == "error"


def test_negative_amount_row_error():
    df, issues = log(["A,2026-03-01,-5,0,0,5", "A,2026-03-02,5,0,0,5"])
    assert len(df) == 1
    assert "NEGATIVE_VALUE" in codes(issues)


def test_duplicate_tid_date_aggregated():
    df, issues = log(["A,2026-03-01,1000,100,0,900", "A,2026-03-01,900,50,200,1050"])
    assert len(df) == 1
    r = df.iloc[0]
    assert (r.opening_balance, r.closing_balance, r.withdrawal, r.replenishment) == (1000, 1050, 150, 200)
    dup = [i for i in issues if i.code == "DUPLICATE_KEY"]
    assert len(dup) == 1 and dup[0].severity == "info"


def test_missing_required_column_raises():
    with pytest.raises(UnreadableFile) as e:
        read_table(b"tid,date,opening_balance\nA,2026-03-01,1\n", "a.csv", "log")
    assert e.value.issues[0].code == "MISSING_COLUMN"


def test_derive_withdrawal_and_replenishment():
    hdr = "tid,date,opening_balance,closing_balance"
    rows = [
        "A,2026-03-01,500000000,450000000",
        "A,2026-03-02,450000000,380000000",
        "A,2026-03-03,380000000,980000000",
        "A,2026-03-04,980000000,900000000",
    ]
    df, _ = read_table(csv_bytes(rows, hdr=hdr), "a.csv", "log", capacities={"A": 1_000_000_000})
    assert (df["source"] == "derived").all()
    assert list(df["withdrawal"]) == [50_000_000, 70_000_000, 60_000_000, 80_000_000]
    assert list(df["replenishment"]) == [0, 0, 660_000_000, 0]
    # capacity falls back to max observed balance when not provided
    df2, _ = read_table(csv_bytes(rows, hdr=hdr), "a.csv", "log")
    assert list(df2["replenishment"]) == [0, 0, 660_000_000, 0]


def test_derive_uses_same_weekday_median():
    hdr = "tid,date,opening_balance,closing_balance"
    rows = []
    bal = 900
    for k in range(9):  # 03-01 .. 03-09: withdrawal 10 on 03-01 and 03-08, else 5
        w = 10 if k in (0, 7) else 5
        rows.append(f"A,{date(2026, 3, 1 + k)},{bal},{bal - w}")
        bal -= w
    rows.append(f"A,2026-03-10,{bal},{bal + 500}")  # jump; same weekday 03-03 had w=5
    df, _ = read_table(csv_bytes(rows, hdr=hdr), "a.csv", "log", capacities={"A": 1000})
    last = df.iloc[-1]
    assert last.withdrawal == 5 and last.replenishment == 505


def test_xlsx_first_sheet():
    wb = Workbook()
    ws = wb.active
    ws.append(HDR.split(","))
    for r in ROWS:
        t, d, *nums = r.split(",")
        ws.append([t, d, *[int(n) for n in nums]])
    wb.create_sheet("other").append(["junk"])
    buf = io.BytesIO()
    wb.save(buf)
    x, _ = read_table(buf.getvalue(), "a.xlsx", "log")
    c, _ = read_table(csv_bytes(ROWS), "a.csv", "log")
    pd.testing.assert_frame_equal(x, c)


def test_unknown_column_info():
    df, issues = read_table(csv_bytes([r + ",z" for r in ROWS], hdr=HDR + ",Extra"), "a.csv", "log")
    assert list(df.columns) == [*LOG_COLS, "source"]
    unk = [i for i in issues if i.code == "UNKNOWN_COLUMN"]
    assert len(unk) == 1 and unk[0].severity == "info"


def test_master_and_holidays_kinds():
    m = (
        "tid,capacity,min_safe_balance,replenish_cycle_days,denomination,cost_per_visit,current_fill_level\n"
        "A,1000,100,4,100000,1500000,900\n"
    )
    df, issues = read_table(m.encode(), "m.csv", "master")
    assert df.iloc[0]["capacity"] == 1000 and df.iloc[0]["next_visit_date"] is None and issues == []
    h = "date,name,type\n2026-12-25,Christmas,christmas\n"
    df, issues = read_table(h.encode(), "h.csv", "holidays")
    assert df.iloc[0]["date"] == date(2026, 12, 25) and issues == []
    with pytest.raises(UnreadableFile):
        read_table(b"tid,capacity\nA,1\n", "m.csv", "master")


@pytest.mark.parametrize(
    ("name", "kind", "rows"),
    [
        ("atm_daily_log.csv", "log", 7300),
        ("atm_master.csv", "master", None),
        ("holidays_id.csv", "holidays", None),
    ],
)
def test_seed_files_load_clean(seed_dir, name, kind, rows):
    df, issues = read_table((seed_dir / name).read_bytes(), name, kind)
    assert not [i for i in issues if i.severity == "error"]
    if rows:
        assert len(df) == rows
