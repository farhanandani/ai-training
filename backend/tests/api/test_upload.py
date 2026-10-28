"""POST /api/data/upload (Task 15): modes, validation issues, aliases, size limit. Fast fake forecasts."""

import io

import openpyxl
import pytest
from fastapi.testclient import TestClient
from test_services import _fast_run_tid

import engine.forecast as F
from app.main import create_app
from app.settings import Settings

LOG_CSV = "atm_daily_log.csv"
TID = "TID-JKT-0001"


def _upload(client, name, content, kind="log", mode=None):
    data = {"kind": kind} if mode is None else {"kind": kind, "mode": mode}
    return client.post("/api/data/upload", files={"file": (name, content)}, data=data)


def _codes(issues, code):
    return [i for i in issues if i["code"] == code]


def test_upload_replace_valid_csv(client, seed_dir):
    """AC6: a §4.1 CSV replaces the data; the dummy ground truth is dropped."""
    r = _upload(client, LOG_CSV, (seed_dir / LOG_CSV).read_bytes(), mode="replace")
    assert r.status_code == 200
    b = r.json()
    assert set(b) == {"dataset_version", "issues", "job"}
    assert not [i for i in b["issues"] if i["severity"] == "error"]
    ctx = client.get("/api/context").json()
    assert ctx["data_source"] == LOG_CSV
    assert client.app.state.store.get_true_demand() is None
    rows = client.get(f"/api/data/log?tid={TID}&from=2026-03-06&to=2026-03-06").json()["rows"]
    assert rows[0]["source"] == "upload"
    assert client.get("/api/data/log").json()["total"] == 7300


def test_upload_merge_label(client):
    body = "tid,date,opening_balance,withdrawal,replenishment,closing_balance\n"
    body += f"{TID},2026-03-06,500000000,100000000,0,400000000\n"
    assert client.app.state.store.get_true_demand() is not None
    assert _upload(client, "fix.csv", body.encode()).status_code == 200  # mode defaults to merge
    assert client.app.state.store.get_true_demand() is None  # TR-16: merged client data drops ground truth
    assert client.get("/api/context").json()["data_source"] == "Dummy data + fix.csv"
    assert client.get("/api/data/log").json()["total"] == 7300
    assert _upload(client, "again.csv", body.encode(), mode="merge").status_code == 200
    assert client.get("/api/context").json()["data_source"] == "Dummy data + fix.csv"


def test_upload_broken_rows(client):
    body = "tid,date,opening_balance,withdrawal,replenishment,closing_balance\n"
    body += f"{TID},2026-13-45,500000000,100000000,0,400000000\n"
    body += f"{TID},yesterday,500000000,100000000,0,400000000\n"
    body += f"{TID},2026-03-05,500000000,-100000000,0,400000000\n"
    body += f"{TID},2026-03-06,400000000,111000000,0,289000000\n"
    body += f"{TID},2026-03-07,289000000,89000000,0,200000000\n"
    r = _upload(client, "broken.csv", body.encode())
    assert r.status_code == 200
    issues = r.json()["issues"]
    assert len(_codes(issues, "BAD_DATE")) == 2
    assert len(_codes(issues, "NEGATIVE_VALUE")) == 1
    got = client.get(f"/api/data/log?tid={TID}&from=2026-03-05&to=2026-03-07").json()["rows"]
    by_date = {x["date"]: x for x in got}
    assert by_date["2026-03-06"]["withdrawal"] == 111_000_000
    assert by_date["2026-03-07"]["withdrawal"] == 89_000_000
    assert by_date["2026-03-05"]["source"] == "dummy"  # the negative row was not stored
    stored = client.get("/api/data/validation").json()["issues"]
    assert len(_codes(stored, "BAD_DATE")) == 2


def test_upload_missing_column_422(client):
    v0 = client.get("/api/context").json()["dataset_version"]
    body = b"tid,date,opening_balance\nTID-JKT-0001,2026-03-06,1\n"
    r = _upload(client, "bad.csv", body)
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "MISSING_COLUMN"
    assert err["details"]["issues"][0]["code"] == "MISSING_COLUMN"
    assert "closing_balance" in err["details"]["issues"][0]["message"]
    assert client.get("/api/context").json()["dataset_version"] == v0  # nothing written


def test_upload_bad_kind_or_mode_400(client):
    assert _upload(client, "a.csv", b"x", kind="other").status_code == 400
    assert _upload(client, "a.csv", b"x", mode="append").status_code == 400


def test_upload_unknown_tid_infers_master(client, seed_dir):
    """AC10: unknown TIDs get an inferred master row and are forecast."""
    src = (seed_dir / LOG_CSV).read_text(encoding="utf-8").splitlines()
    rows = [ln.replace(TID, "TID-NEW-0011") for ln in src[1:] if ln.startswith(TID + ",")]
    r = _upload(client, "new.csv", "\n".join([src[0], *rows]).encode())
    assert r.status_code == 200
    b = r.json()
    assert _codes(b["issues"], "UNKNOWN_TID")[0]["tid"] == "TID-NEW-0011"
    master = {m["tid"]: m for m in client.get("/api/data/master").json()["rows"]}
    assert master["TID-NEW-0011"]["inferred"] is True
    assert master[TID]["inferred"] is False
    assert "TID-NEW-0011" in b["job"]["pending_tids"]
    assert client.app.state.services.runner.wait(b["job"]["job_id"], timeout=60)
    fleet = client.get("/api/fleet?as_of=2026-03-06&h=21&sl=p90").json()
    row = {a["tid"]: a for a in fleet["atms"]}["TID-NEW-0011"]
    assert row["inferred_master"] is True
    assert row["recommended_amount"] is not None


def test_upload_semicolon_rp_prefix(client):
    """Review Focus 1: id-ID export -> one row-level BAD_AMOUNT, the rest stored, never a 500."""
    lines = ["tid;date;opening_balance;withdrawal;replenishment;closing_balance"]
    lines.append(f"{TID};06/03/2026;Rp 400000000;Rp 111000000;Rp 0;Rp 289000000")
    lines.append(f"{TID};07/03/2026;Rp 289000000;1.000.000;0;Rp 288000000")
    lines.append(f"{TID};08/03/2026;Rp 289000000;Rp 89000000;Rp 0;Rp 200000000")
    r = _upload(client, "idr.csv", "\n".join(lines).encode())
    assert r.status_code == 200
    issues = r.json()["issues"]
    assert len(_codes(issues, "BAD_AMOUNT")) == 1
    got = client.get(f"/api/data/log?tid={TID}&from=2026-03-06&to=2026-03-08").json()["rows"]
    by_date = {x["date"]: x for x in got}
    assert by_date["2026-03-06"]["withdrawal"] == 111_000_000
    assert by_date["2026-03-08"]["closing_balance"] == 200_000_000
    assert by_date["2026-03-07"]["source"] == "dummy"


def test_upload_xlsx_alias_headers(client):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Terminal ID", "Tanggal", "Saldo Awal", "Penarikan", "Isi Ulang", "Saldo Akhir", "Cabang"])
    ws.append([TID, "2026-03-06", 400_000_000, 111_000_000, 0, 289_000_000, "Jakarta"])
    buf = io.BytesIO()
    wb.save(buf)
    r = _upload(client, "export.xlsx", buf.getvalue())
    assert r.status_code == 200
    assert _codes(r.json()["issues"], "UNKNOWN_COLUMN")
    got = client.get(f"/api/data/log?tid={TID}&from=2026-03-06&to=2026-03-06").json()["rows"][0]
    assert got["withdrawal"] == 111_000_000 and got["source"] == "upload"


def test_upload_master_and_holidays(client):
    m = client.get("/api/data/download?kind=master").text.replace("Grand Indonesia Mall", "GI Mall")
    r = _upload(client, "master.csv", m.encode(), kind="master")
    assert r.status_code == 200
    names = {x["tid"]: x["location_name"] for x in client.get("/api/data/master").json()["rows"]}
    assert names[TID] == "GI Mall"
    h = client.get("/api/data/download?kind=holidays").text + "2027-12-31,Test,national\n"
    r = _upload(client, "hol.csv", h.encode(), kind="holidays", mode="replace")
    assert r.status_code == 200
    assert client.get("/api/data/holidays").json()["rows"][-1]["date"] == "2027-12-31"
    bad = "date,name,type\n2027-12-30,Party,party\n2027-12-29,Ok,national\n"
    r = _upload(client, "hol2.csv", bad.encode(), kind="holidays")
    assert r.status_code == 200
    assert _codes(r.json()["issues"], "BAD_VALUE")


@pytest.fixture
def small_client(tmp_path, seed_dir, monkeypatch):
    monkeypatch.setattr(F, "run_tid", _fast_run_tid)
    s = Settings(
        workspace_db=tmp_path / "ws" / "workspace.db", seed_dir=seed_dir, workers=2, max_upload_mb=0.001
    )
    with TestClient(create_app(s, start_warmup=False, runner_mode="thread")) as c:
        yield c


def test_upload_too_large_413(small_client):
    r = _upload(small_client, "big.csv", b"x" * 2000)
    assert r.status_code == 413
    assert r.json()["error"]["code"] == "FILE_TOO_LARGE"


def test_replace_upload_clears_cache_full_run(client, seed_dir, monkeypatch):
    """A log replace is a new dataset: the next forecasts are full runs, never incremental refits."""
    q = "as_of=2026-03-06&h=21&sl=p90"
    job = client.get(f"/api/fleet?{q}").json()["job_id"]
    assert client.app.state.services.runner.wait(job, timeout=60)
    full = []
    monkeypatch.setattr(F, "run_tid", lambda tid, *a: full.append(tid) or _fast_run_tid(tid, *a))
    monkeypatch.setattr(F, "run_tid_incremental", lambda *a: pytest.fail("incremental after replace"))
    lines = (seed_dir / LOG_CSV).read_text(encoding="utf-8").splitlines()
    i = next(k for k, ln in enumerate(lines) if ln.startswith(f"{TID},2026-03-06,"))
    f = lines[i].split(",")
    f[3] = str(int(f[3]) * 3)  # withdrawal x3 (identity broken; stored with a warning)
    lines[i] = ",".join(f)
    r = _upload(client, "client.csv", "\n".join(lines).encode(), mode="replace")
    assert r.status_code == 200
    b = r.json()
    assert TID in b["job"]["pending_tids"]  # cache cleared: every un-memoised TID is recomputed
    assert client.app.state.services.runner.wait(b["job"]["job_id"], timeout=60)
    assert sorted(full) == b["job"]["pending_tids"]  # all full runs, none incremental
    assert client.app.state.services.runner.status(b["job"]["job_id"])["failed"] == []


@pytest.mark.parametrize(
    ("kind", "body"),
    [
        (
            "master",
            (
                "tid,capacity,min_safe_balance,replenish_cycle_days,denomination,cost_per_visit,"
                "current_fill_level\nTID-X,1,1,1,20000,1,1\n"
            ),
        ),
        ("holidays", "date,name,type\n2027-12-30,Party,party\n"),
    ],
)
def test_merge_with_no_valid_rows_writes_nothing(client, kind, body):
    v0 = client.get("/api/context").json()["dataset_version"]
    r = _upload(client, "x.csv", body.encode(), kind=kind)
    assert r.status_code == 200
    assert _codes(r.json()["issues"], "BAD_VALUE")
    assert r.json()["dataset_version"] == v0
    assert client.get("/api/context").json()["dataset_version"] == v0
