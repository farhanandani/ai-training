"""Planner API (Task 14): POST /api/plan, PUT/DELETE /api/plan/overrides, GET /api/plan/export.csv."""

import csv
import io
import time
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from test_services import AS_OF

from app.main import create_app
from app.settings import Settings
from engine.schema import Override

BODY = {"as_of": AS_OF.isoformat(), "h": 21, "sl": "p90", "budget": None}
Q = f"as_of={AS_OF.isoformat()}&h=21&sl=p90"
TID = "TID-JKT-0001"


def _warm(client):
    j = client.post("/api/plan", json=BODY).json()["job_id"]
    if j:
        client.app.state.services.runner.wait(j, timeout=60)
    return client.post("/api/plan", json=BODY).json()


def test_plan_unconstrained_funded_100pct(client):
    b = _warm(client)
    assert b["pending_tids"] == [] and b["budget"] is None
    assert b["funded_pct"] == 1.0 and b["funded_total"] == b["need_total"] > 0
    assert set(b) >= {"need_total", "funded_total", "funded_pct", "underfunded", "unused", "visits"}
    assert set(b) >= {"reallocation", "comparison"}
    s = client.get("/api/settings").json()
    assert (s["h"], s["sl"], s["budget"]) == (21, "p90", None)


def test_plan_saves_inputs_and_validates(client):
    b = _warm(client)
    r = client.post("/api/plan", json={**BODY, "budget": b["need_total"] // 2})
    assert r.status_code == 200
    assert client.get("/api/settings").json()["budget"] == b["need_total"] // 2
    assert r.json()["funded_total"] <= b["need_total"] // 2
    for bad in ({**BODY, "budget": -1}, {**BODY, "h": 3}, {**BODY, "sl": "p42"}):
        r = client.post("/api/plan", json=bad)
        assert r.status_code == 400 and r.json()["error"]["code"] == "BAD_PARAMS"
    r = client.post("/api/plan", json={**BODY, "as_of": "2020-01-01"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "AS_OF_OUT_OF_RANGE"


@pytest.mark.slow
def test_plan_70pct_budget(tmp_path, seed_dir):
    """AC7 via API with the real worker."""
    s = Settings(workspace_db=tmp_path / "ws" / "workspace.db", seed_dir=seed_dir, workers=4)
    with TestClient(create_app(s, start_warmup=False, runner_mode="process")) as c:
        j = c.post("/api/plan", json=BODY).json()["job_id"]
        assert j is None or c.app.state.services.runner.wait(j, timeout=600)
        full = c.post("/api/plan", json=BODY).json()
        assert full["pending_tids"] == []
        budget = int(full["need_total"] * 0.7)
        b = c.post("/api/plan", json={**BODY, "budget": budget}).json()
        assert b["funded_total"] <= budget
        assert b["reallocation"]


def test_override_applied_then_cleared(client):
    base = _warm(client)
    v0 = next(v for v in base["visits"] if v["tid"] == TID)
    ov = {"tid": TID, "visit_date": v0["date"], "amount": 123_000_000}
    # assert client.put("/api/plan/overrides", json={"overrides": [ov]}).json() == {"ok": True}
    assert client.put("/api/plan/overrides", json={**WIN, "overrides": [ov]}).json() == {"ok": True}
    v = next(
        v
        for v in client.post("/api/plan", json=BODY).json()["visits"]
        if v["tid"] == TID and v["date"] == v0["date"]
    )
    assert v["manual"] is True and v["override"]["amount"] == 123_000_000
    # # upsert: same key replaced, others untouched
    # replace: the window's set is replaced by the new one
    # client.put("/api/plan/overrides", json={"overrides": [{**ov, "amount": 5_000_000}]})
    client.put("/api/plan/overrides", json={**WIN, "overrides": [{**ov, "amount": 5_000_000}]})
    assert [o.amount for o in client.app.state.store.get_overrides()] == [5_000_000]
    assert client.delete("/api/plan/overrides").json() == {"ok": True}
    assert client.app.state.store.get_overrides() == []
    v = next(
        v
        for v in client.post("/api/plan", json=BODY).json()["visits"]
        if v["tid"] == TID and v["date"] == v0["date"]
    )
    assert v["manual"] is False and v["override"] is None


def test_override_validation(client):
    _warm(client)
    # r = client.put(
    #     "/api/plan/overrides", json={"overrides": [{"tid": "TID-NOPE", "visit_date": "2026-03-10"}]}
    # )
    r = client.put(
        "/api/plan/overrides", json={**WIN, "overrides": [{"tid": "TID-NOPE", "visit_date": "2026-03-10"}]}
    )
    assert r.status_code == 404 and r.json()["error"]["code"] == "UNKNOWN_TID"
    # r = client.put(
    #     "/api/plan/overrides", json={"overrides": [{"tid": TID, "visit_date": "2026-03-10", "amount": -5}]}
    # )
    r = client.put(
        "/api/plan/overrides",
        json={**WIN, "overrides": [{"tid": TID, "visit_date": "2026-03-10", "amount": -5}]},
    )
    assert r.status_code == 400 and r.json()["error"]["code"] == "BAD_PARAMS"
    r = client.put("/api/plan/overrides", json={"overrides": []})  # the plan window is required
    assert r.status_code == 400 and r.json()["error"]["code"] == "BAD_PARAMS"
    assert client.app.state.store.get_overrides() == []


def test_export_csv_header_and_rows(client):
    b = _warm(client)
    v0 = next(v for v in b["visits"] if v["tid"] == TID)
    client.put(
        "/api/plan/overrides",
        # json={"overrides": [{"tid": TID, "visit_date": v0["date"], "amount": 123_000_000}]},
        json={**WIN, "overrides": [{"tid": TID, "visit_date": v0["date"], "amount": 123_000_000}]},
    )
    r = client.get(f"/api/plan/export.csv?{Q}")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert f'filename="replenishment-plan-{AS_OF.isoformat()}.csv"' in r.headers["content-disposition"]
    assert r.headers["content-disposition"].startswith("attachment")
    rows = list(csv.reader(io.StringIO(r.text)))
    assert rows[0] == ["tid", "visit_date", "amount", "source"]
    body = rows[1:]
    assert body == sorted(body, key=lambda x: (x[0], x[1]))
    plan = client.post("/api/plan", json=BODY).json()
    live = [v for v in plan["visits"] if "skip" not in v["flags"]]
    assert len(body) == len(live)
    assert [TID, v0["date"], "123000000", "manual"] in body
    assert {x[3] for x in body} <= {"recommended", "extra", "manual"}


@pytest.mark.perf
def test_plan_latency(client):
    _warm(client)
    t = time.perf_counter()
    assert client.post("/api/plan", json=BODY).status_code == 200
    assert time.perf_counter() - t <= 0.3


WIN = {"as_of": AS_OF.isoformat(), "h": 21}


def _visits(client, tid=TID):
    return [v for v in client.post("/api/plan", json=BODY).json()["visits"] if v["tid"] == tid]


def _put(client, overrides):
    r = client.put("/api/plan/overrides", json={**WIN, "overrides": overrides})
    assert r.status_code == 200, r.text
    return r


def test_override_unskip_clears_the_skip(client):
    # F2: the frontend sends the complete desired set; an un-skipped row is no longer in it.
    _warm(client)
    v0 = next(v for v in _visits(client) if "skip" not in v["flags"])
    _put(client, [{"tid": TID, "visit_date": v0["date"], "skipped": True}])
    v = next(v for v in _visits(client) if v["date"] == v0["date"])
    assert "skip" in v["flags"] and v["override"]["skipped"] is True
    _put(client, [])
    v = next(v for v in _visits(client) if v["date"] == v0["date"])
    assert "skip" not in v["flags"] and v["override"] is None and v["manual"] is False
    assert client.app.state.store.get_overrides() == []
    # a no-op row (no amount, not skipped, not moved) is dropped too
    _put(client, [{"tid": TID, "visit_date": v0["date"], "skipped": False}])
    assert client.app.state.store.get_overrides() == []


def test_override_move_twice_leaves_one_moved_visit(client):
    # F3: moving a visit twice must not leave the first move's row behind (phantom Rp 0 'Manual visit').
    _warm(client)
    before = _visits(client)
    v0 = next(v for v in before if "skip" not in v["flags"])
    d0 = date.fromisoformat(v0["date"])
    taken = {v["date"] for v in before}
    d1, d2 = [d for d in (d0 + timedelta(days=k) for k in range(1, 20)) if d.isoformat() not in taken][:2]
    _put(client, [{"tid": TID, "visit_date": d1.isoformat(), "moved_from": d0.isoformat()}])
    _put(client, [{"tid": TID, "visit_date": d2.isoformat(), "moved_from": d0.isoformat()}])
    after = _visits(client)
    assert len(after) == len(before)
    moved = [v for v in after if v["manual"]]
    assert [(v["date"], v["kind"]) for v in moved] == [(d2.isoformat(), "moved")]
    assert not any(v["reason"] == "Manual visit" for v in after)
    assert len(client.app.state.store.get_overrides()) == 1


def test_override_move_back_to_original_leaves_no_override(client):
    _warm(client)
    before = _visits(client)
    v0 = next(v for v in before if "skip" not in v["flags"])
    d0 = date.fromisoformat(v0["date"])
    d1 = next(
        d
        for d in (d0 + timedelta(days=k) for k in range(1, 20))
        if d.isoformat() not in {v["date"] for v in before}
    )
    _put(client, [{"tid": TID, "visit_date": d1.isoformat(), "moved_from": d0.isoformat()}])
    _put(client, [{"tid": TID, "visit_date": d0.isoformat(), "moved_from": d0.isoformat()}])
    assert client.app.state.store.get_overrides() == []
    assert [(v["date"], v["manual"]) for v in _visits(client)] == [(v["date"], False) for v in before]


def test_override_replace_keeps_rows_outside_the_window(client):
    _warm(client)
    store = client.app.state.store
    outside = Override(TID, AS_OF + timedelta(days=40), 7_000_000)
    store.put_overrides([outside])
    _put(client, [])
    assert store.get_overrides() == [outside]


def test_export_uses_the_budget_param(client):
    # F4: the export reflects the on-screen budget (query param), not the last persisted one.
    b = _warm(client)
    budget = b["need_total"] * 7 // 10 // 100_000 * 100_000
    plan = client.post("/api/plan", json={**BODY, "budget": budget}).json()
    client.post("/api/plan", json={**BODY, "persist": False})  # the base (unconstrained) query lands last
    r = client.get(f"/api/plan/export.csv?{Q}&budget={budget}")
    assert r.status_code == 200
    rows = list(csv.reader(io.StringIO(r.text)))[1:]
    want = [[v["tid"], v["date"], str(v["allocated"])] for v in plan["visits"] if "skip" not in v["flags"]]
    assert [x[:3] for x in rows] == want
    assert sum(int(x[2]) for x in rows) == plan["funded_total"] < b["need_total"]
    # empty / absent budget = unconstrained
    for q in (Q, f"{Q}&budget="):
        rows = list(csv.reader(io.StringIO(client.get(f"/api/plan/export.csv?{q}").text)))[1:]
        assert sum(int(x[2]) for x in rows) == b["need_total"]
    r = client.get(f"/api/plan/export.csv?{Q}&budget=abc")
    assert r.status_code == 400 and r.json()["error"]["code"] == "BAD_PARAMS"


def test_plan_persist_false_keeps_settings(client):
    b = _warm(client)
    client.post("/api/plan", json={**BODY, "budget": b["need_total"] // 2})
    client.post("/api/plan", json={**BODY, "h": 14, "persist": False})
    s = client.get("/api/settings").json()
    assert (s["h"], s["budget"]) == (21, b["need_total"] // 2)


def test_export_pending_is_409(client):
    r = client.get(f"/api/plan/export.csv?{Q}")
    assert r.status_code == 409 and r.json()["error"]["code"] == "PENDING"
    assert r.json()["error"]["details"]["pending_tids"]
