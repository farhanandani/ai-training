"""Data API (Task 15): grid read/edit, master/holidays, validation, download, reset. Fast fake forecasts."""

import io
import time

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from test_services import AS_OF, TIDS

from app.main import create_app
from app.settings import Settings

Q = f"as_of={AS_OF.isoformat()}&h=21&sl=p90"
TID = "TID-JKT-0001"


def _warm(client):
    """Cache forecasts for every TID at AS_OF (also makes AS_OF the server's current as_of)."""
    body = client.get(f"/api/fleet?{Q}").json()
    if body.get("job_id"):
        assert client.app.state.services.runner.wait(body["job_id"], timeout=60)
    body = client.get(f"/api/fleet?{Q}").json()
    assert body["pending_tids"] == []
    return body


def _row(client, tid, d):
    r = client.get(f"/api/data/log?tid={tid}&from={d}&to={d}").json()
    assert r["total"] == 1
    return r["rows"][0]


def _assert_write_body(b):
    assert set(b) == {"dataset_version", "issues", "job"}
    assert set(b["job"]) == {"job_id", "pending_tids"}


# ------------------------------------------------------------------- grid read
def test_get_log_paging_and_filters(client):
    r = client.get("/api/data/log")
    assert r.status_code == 200
    b = r.json()
    assert b["total"] == 7300
    assert len(b["rows"]) == 200
    first = b["rows"][0]
    assert set(first) == {
        "tid",
        "date",
        "opening_balance",
        "withdrawal",
        "replenishment",
        "closing_balance",
        "source",
    }
    assert (first["tid"], first["date"]) == ("TID-BAL-0010", "2024-10-28")
    p2 = client.get("/api/data/log?page=2&page_size=1000").json()
    assert len(p2["rows"]) == 1000
    assert (p2["rows"][0]["tid"], p2["rows"][0]["date"]) == ("TID-BKS-0005", "2025-07-25")
    f = client.get(f"/api/data/log?tid={TID}&from=2026-03-01&to=2026-03-06").json()
    assert f["total"] == 6
    assert [x["date"] for x in f["rows"]] == [f"2026-03-0{i}" for i in range(1, 7)]
    assert client.get("/api/data/log?page_size=1001").status_code == 400
    assert client.get("/api/data/log?page=0").status_code == 400


# ------------------------------------------------------------------ row edits
def test_patch_row_recompute_only_that_tid(client):
    """AC5: editing one TID's row only re-forecasts that TID."""
    _warm(client)
    before = _row(client, TID, "2026-03-06")
    v0 = client.get("/api/context").json()["dataset_version"]
    r = client.patch(
        "/api/data/log",
        json={"rows": [{"tid": TID, "date": "2026-03-06", "withdrawal": before["withdrawal"] * 3}]},
    )
    assert r.status_code == 200
    b = r.json()
    _assert_write_body(b)
    assert b["job"]["pending_tids"] == [TID]
    assert b["job"]["job_id"]
    assert b["dataset_version"] > v0
    after = _row(client, TID, "2026-03-06")
    assert after["withdrawal"] == before["withdrawal"] * 3
    assert after["source"] == "edit"
    # fields not given keep their stored values
    for c in ("opening_balance", "replenishment", "closing_balance"):
        assert after[c] == before[c]


def test_patch_breaking_identity_saved_with_warning(client):
    r = client.patch(
        "/api/data/log",
        json={"rows": [{"tid": TID, "date": "2026-03-06", "closing_balance": 123_400_000}]},
    )
    assert r.status_code == 200
    issues = r.json()["issues"]
    assert any(
        i["code"] == "BALANCE_IDENTITY" and i["tid"] == TID and i["date"] == "2026-03-06" for i in issues
    )
    assert _row(client, TID, "2026-03-06")["closing_balance"] == 123_400_000  # saved, not fixed
    stored = client.get("/api/data/validation").json()["issues"]
    assert any(i["code"] == "BALANCE_IDENTITY" and i["date"] == "2026-03-06" for i in stored)


def test_patch_unknown_row_404_and_negative_400(client):
    r = client.patch("/api/data/log", json={"rows": [{"tid": "TID-NOPE", "date": "2026-03-06"}]})
    assert r.status_code == 404
    r = client.patch("/api/data/log", json={"rows": [{"tid": TID, "date": "2030-01-01", "withdrawal": 1}]})
    assert r.status_code == 404
    r = client.patch("/api/data/log", json={"rows": [{"tid": TID, "date": "2026-03-06", "withdrawal": -1}]})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "BAD_PARAMS"


def test_post_and_delete_log_rows(client):
    row = {
        "tid": TID,
        "date": "2026-10-28",
        "opening_balance": 500_000_000,
        "withdrawal": 100_000_000,
        "replenishment": 0,
        "closing_balance": 400_000_000,
    }
    r = client.post("/api/data/log", json={"rows": [row]})
    assert r.status_code == 200
    _assert_write_body(r.json())
    got = _row(client, TID, "2026-10-28")
    assert got["withdrawal"] == 100_000_000 and got["source"] == "edit"
    r = client.request("DELETE", "/api/data/log", json={"keys": [{"tid": TID, "date": "2026-10-28"}]})
    assert r.status_code == 200
    _assert_write_body(r.json())
    assert client.get(f"/api/data/log?tid={TID}&from=2026-10-28").json()["total"] == 0


def test_post_unknown_tid_infers_master(client):
    rows = [
        {
            "tid": "TID-NEW-0100",
            "date": f"2026-03-0{d}",
            "opening_balance": 300_000_000,
            "withdrawal": 50_000_000,
            "replenishment": 0,
            "closing_balance": 250_000_000,
        }
        for d in (1, 2)
    ]
    r = client.post("/api/data/log", json={"rows": rows})
    assert r.status_code == 200
    assert any(i["code"] == "UNKNOWN_TID" and i["tid"] == "TID-NEW-0100" for i in r.json()["issues"])
    m = {x["tid"]: x for x in client.get("/api/data/master").json()["rows"]}
    assert m["TID-NEW-0100"]["inferred"] is True


# ------------------------------------------------------------ master/holidays
def test_master_get_put(client):
    rows = client.get("/api/data/master").json()["rows"]
    assert len(rows) == 10 and rows[0]["tid"] == "TID-BAL-0010"
    edited = {**rows[0], "min_safe_balance": rows[0]["min_safe_balance"] + 1_000_000}
    r = client.put("/api/data/master", json={"rows": [edited]})
    assert r.status_code == 200
    _assert_write_body(r.json())
    again = {x["tid"]: x for x in client.get("/api/data/master").json()["rows"]}
    assert again[edited["tid"]]["min_safe_balance"] == edited["min_safe_balance"]
    assert len(again) == 10  # upsert: other rows kept
    bad = {**rows[0], "denomination": 20_000}
    assert client.put("/api/data/master", json={"rows": [bad]}).status_code == 400


def test_holidays_get_put(client):
    rows = client.get("/api/data/holidays").json()["rows"]
    assert rows and set(rows[0]) == {"date", "name", "type"}
    new = [*rows, {"date": "2027-12-31", "name": "Test Day", "type": "national"}]
    r = client.put("/api/data/holidays", json={"rows": new})
    assert r.status_code == 200
    _assert_write_body(r.json())
    got = client.get("/api/data/holidays").json()["rows"]
    assert got[-1]["date"] == "2027-12-31" and len(got) == len(rows) + 1
    bad = [{"date": "2027-12-31", "name": "x", "type": "party"}]
    assert client.put("/api/data/holidays", json={"rows": bad}).status_code == 400


# ------------------------------------------------------------ download/reset
@pytest.mark.parametrize(
    ("kind", "header", "n"),
    [
        ("log", "tid,date,opening_balance,withdrawal,replenishment,closing_balance", 7300),
        (
            "master",
            (
                "tid,location_name,location_type,capacity,min_safe_balance,replenish_cycle_days,"
                "denomination,cost_per_visit,current_fill_level,next_visit_date"
            ),
            10,
        ),
        ("holidays", "date,name,type", None),
    ],
)
def test_download_canonical_csv(client, kind, header, n):
    r = client.get(f"/api/data/download?kind={kind}")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    lines = r.text.splitlines()
    assert lines[0] == header
    if n is not None:
        assert len(lines) == n + 1
    assert client.get("/api/data/download?kind=nope").status_code == 400


def test_download_roundtrips_through_upload(client):
    csv = client.get("/api/data/download?kind=log").content
    df = pd.read_csv(io.BytesIO(csv))
    assert len(df) == 7300
    r = client.post(
        "/api/data/upload",
        files={"file": ("export.csv", csv, "text/csv")},
        data={"kind": "log", "mode": "merge"},
    )
    assert r.status_code == 200


def test_reset_restores_dummy(client):
    orig = _row(client, TID, "2026-03-06")
    client.patch("/api/data/log", json={"rows": [{"tid": TID, "date": "2026-03-06", "withdrawal": 1}]})
    client.post(
        "/api/data/upload",
        files={"file": ("mine.csv", b"tid,date,opening_balance,closing_balance\nX-1,2026-01-01,10,5\n")},
        data={"kind": "log", "mode": "replace"},
    )
    assert client.get("/api/context").json()["data_source"] == "mine.csv"
    r = client.post("/api/data/reset")
    assert r.status_code == 200
    _assert_write_body(r.json())
    assert _row(client, TID, "2026-03-06") == orig
    assert client.get("/api/data/log").json()["total"] == 7300
    assert client.get("/api/context").json()["data_source"] == "Dummy data"
    assert client.app.state.store.get_true_demand() is not None
    assert len(client.get("/api/data/master").json()["rows"]) == 10
    assert client.get("/api/data/validation").json()["issues"] == []


def test_validation_endpoint_shape(client):
    r = client.get("/api/data/validation")
    assert r.status_code == 200
    assert "issues" in r.json()


# --------------------------------------------------------------- real worker
@pytest.mark.slow
def test_patch_row_recompute_real_worker(tmp_path, seed_dir):
    """AC5 / TR-39: one-row edit -> that TID re-forecast within 5 s, its recommendation changes."""
    s = Settings(workspace_db=tmp_path / "ws" / "workspace.db", seed_dir=seed_dir)
    with TestClient(create_app(s, start_warmup=False)) as client:
        svc = client.app.state.services
        before = client.get(f"/api/fleet?{Q}").json()
        assert svc.runner.wait(before["job_id"], timeout=180)
        before = {a["tid"]: a for a in client.get(f"/api/fleet?{Q}").json()["atms"]}
        assert set(before) == set(TIDS)
        w = _row(client, TID, "2026-03-06")["withdrawal"]
        t0 = time.perf_counter()
        b = client.patch(
            "/api/data/log", json={"rows": [{"tid": TID, "date": "2026-03-06", "withdrawal": w * 3}]}
        ).json()
        assert b["job"]["pending_tids"] == [TID]
        assert svc.runner.wait(b["job"]["job_id"], timeout=60)
        elapsed = time.perf_counter() - t0
        print(f"one-row edit -> TID ready: {elapsed:.2f} s")
        after = {a["tid"]: a for a in client.get(f"/api/fleet?{Q}").json()["atms"]}
        assert elapsed <= 5.0
        assert after[TID]["recommended_amount"] != before[TID]["recommended_amount"]
        for t in TIDS:
            if t != TID:
                assert after[t]["recommended_amount"] == before[t]["recommended_amount"]


def test_reset_rewarms_all_scenarios_in_background(client, monkeypatch):
    import threading

    svc = client.app.state.services
    called = threading.Event()
    monkeypatch.setattr(svc, "warmup", lambda wait=False: called.set() or [])
    assert svc.warm_on_reset is False  # create_app(start_warmup=False): tests never warm in the background
    client.post("/api/data/reset")
    assert not called.wait(0.3)
    svc.warm_on_reset = True
    assert client.post("/api/data/reset").status_code == 200
    assert called.wait(5)


def test_create_app_warms_on_reset_when_warmup_enabled(tmp_path, seed_dir):
    s = Settings(workspace_db=tmp_path / "ws" / "workspace.db", seed_dir=seed_dir, workers=1)
    app = create_app(s, start_warmup=True, runner_mode="thread")
    with TestClient(app) as c:
        assert c.app.state.services.warm_on_reset is True
