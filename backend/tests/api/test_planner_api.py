"""Planner API (Task 14): POST /api/plan, PUT/DELETE /api/plan/overrides, GET /api/plan/export.csv."""

import csv
import io
import time

import pytest
from fastapi.testclient import TestClient
from test_services import AS_OF

from app.main import create_app
from app.settings import Settings

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
    assert client.put("/api/plan/overrides", json={"overrides": [ov]}).json() == {"ok": True}
    v = next(
        v
        for v in client.post("/api/plan", json=BODY).json()["visits"]
        if v["tid"] == TID and v["date"] == v0["date"]
    )
    assert v["manual"] is True and v["override"]["amount"] == 123_000_000
    # upsert: same key replaced, others untouched
    client.put("/api/plan/overrides", json={"overrides": [{**ov, "amount": 5_000_000}]})
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
    r = client.put(
        "/api/plan/overrides", json={"overrides": [{"tid": "TID-NOPE", "visit_date": "2026-03-10"}]}
    )
    assert r.status_code == 404 and r.json()["error"]["code"] == "UNKNOWN_TID"
    r = client.put(
        "/api/plan/overrides", json={"overrides": [{"tid": TID, "visit_date": "2026-03-10", "amount": -5}]}
    )
    assert r.status_code == 400 and r.json()["error"]["code"] == "BAD_PARAMS"
    assert client.app.state.store.get_overrides() == []


def test_export_csv_header_and_rows(client):
    b = _warm(client)
    v0 = next(v for v in b["visits"] if v["tid"] == TID)
    client.put(
        "/api/plan/overrides",
        json={"overrides": [{"tid": TID, "visit_date": v0["date"], "amount": 123_000_000}]},
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
