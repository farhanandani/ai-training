"""Read API (Task 13): TestClient, thread-mode runner, fast fake forecasts (no real model fits)."""

from datetime import timedelta

import pandas as pd
import pytest

# from fastapi.testclient import TestClient
# from test_services import AS_OF, TIDS, _fast_run_tid
from test_services import AS_OF, TIDS

# import engine.forecast as F
# from app.main import create_app
# from app.settings import Settings


# @pytest.fixture
# def client(tmp_path, seed_dir, monkeypatch):
#     monkeypatch.setattr(F, "run_tid", _fast_run_tid)
#     s = Settings(workspace_db=tmp_path / "ws" / "workspace.db", seed_dir=seed_dir, workers=2)
#     app = create_app(s, start_warmup=False, runner_mode="thread")
#     with TestClient(app) as c:
#         yield c
# moved to tests/api/conftest.py (shared with test_planner_api.py)


Q = f"as_of={AS_OF.isoformat()}&h=21&sl=p90"


def _warm(client, path="/api/fleet", q=Q):
    body = client.get(f"{path}?{q}").json()
    if body.get("job_id"):
        client.app.state.services.runner.wait(body["job_id"], timeout=60)
    return client.get(f"{path}?{q}").json()


def test_context_defaults(client):
    r = client.get("/api/context")
    assert r.status_code == 200
    b = r.json()
    assert b["as_of_min"] == "2025-12-10"
    assert b["default_scenario"] == "pre_lebaran_2026"
    assert len(b["scenarios"]) == 3
    assert b["tids"] == TIDS and len(b["tids"]) == 10
    assert {s["id"] for s in b["scenarios"]} == {"today", "pre_lebaran_2026", "year_end_2025"}
    assert set(b) >= {"data_source", "min_date", "max_date", "as_of_max", "defaults", "dataset_version"}
    assert b["defaults"]["h"] == 14


def test_fleet_shape(client):
    b = client.get(f"/api/fleet?{Q}").json()
    assert set(b) >= {"as_of", "h", "sl", "dataset_version", "pending_tids", "job_id", "kpis", "atms"}
    assert b["pending_tids"] and b["job_id"]
    assert len(b["atms"]) < 10
    b = _warm(client)
    assert b["pending_tids"] == [] and len(b["atms"]) == 10
    assert set(b["kpis"]) == {"at_risk", "over_stocked", "idle_cash", "recommended_total"}
    assert [a["tid"] for a in b["atms"]] == TIDS
    assert set(b["atms"][0]) >= {
        "tid",
        "location_name",
        "location_type",
        "balance",
        "capacity",
        "days_of_cash",
        "status",
        "next_visit",
        "recommended_amount",
        "inferred_master",
    }


def test_atm_shape(client):
    _warm(client)
    b = client.get(f"/api/atm/TID-JKT-0001?{Q}").json()
    assert set(b) >= {
        "tid",
        "master",
        "status",
        "days_of_cash",
        "history",
        "forecast",
        "actual_after",
        "projection",
        "visits",
        "explanations",
        "model",
        "metrics",
        "holidays_in_view",
    }
    assert len(b["forecast"]) == 21 and set(b["forecast"][0]) == {"date", "q10", "q50", "q80", "q90", "q95"}
    assert set(b["projection"]) == {"current", "recommended"}
    assert b["model"]["name"] == "seasonal_naive"


def test_accuracy_shape(client):
    _warm(client)
    b = client.get(f"/api/accuracy?as_of={AS_OF.isoformat()}&h=14").json()
    assert [a["tid"] for a in b["atms"]] == TIDS
    assert set(b["atms"][0]) >= {"tid", "status", "model", "metrics", "candidates", "backtest"}


def test_status_endpoint(client):
    job = client.get(f"/api/fleet?{Q}").json()["job_id"]
    client.app.state.services.runner.wait(job, timeout=60)
    b = client.get(f"/api/status?job_id={job}").json()
    assert b["done"] is True and b["total"] == 10 and b["failed"] == []
    assert client.get("/api/status?job_id=nope").status_code == 404


def test_atm_unknown_404(client):
    r = client.get(f"/api/atm/TID-NOPE?{Q}")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "UNKNOWN_TID"


def test_as_of_out_of_range_409(client):
    r = client.get("/api/fleet?as_of=2020-01-01&h=14&sl=p90")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "AS_OF_OUT_OF_RANGE"


@pytest.mark.parametrize("q", ["h=45", "h=3", "h=abc", "sl=p42", "as_of=notadate"])
def test_bad_params_400(client, q):
    r = client.get(f"/api/fleet?as_of={AS_OF.isoformat()}&{q}")
    assert r.status_code == 400
    e = r.json()["error"]
    assert e["code"] == "BAD_PARAMS" and "message" in e and "details" in e


def test_fleet_with_short_history_tid(client):
    from engine.schema import LOG_COLS, AtmMaster

    store = client.app.state.store
    store.put_master(
        [
            AtmMaster(
                "TID-NEW-1", "New Mall", "mall", 800_000_000, 50_000_000, 7, 100_000, 1_500_000, 700_000_000
            )
        ]
    )
    days = [AS_OF - timedelta(days=i) for i in range(99, -1, -1)]
    log = pd.DataFrame(
        {
            "tid": "TID-NEW-1",
            "date": days,
            "opening_balance": 500_000_000,
            "withdrawal": 10_000_000,
            "replenishment": 0,
            "closing_balance": 490_000_000,
        }
    )[LOG_COLS]
    store.upsert_log(log, "upload")
    b = _warm(client)
    rows = {a["tid"]: a for a in b["atms"]}
    assert len(rows) == 11
    assert rows["TID-NEW-1"]["status"] == "insufficient_history"
    assert all(r["status"] != "insufficient_history" for t, r in rows.items() if t != "TID-NEW-1")


def test_settings_range_and_no_refit(client):
    _warm(client)
    g = client.get("/api/settings").json()
    assert set(g) == {"overstock_frac", "idle_rate", "detect_jump_frac", "h", "sl", "budget"}
    assert client.put("/api/settings", json={"overstock_frac": 0.95}).status_code == 400
    assert client.put("/api/settings", json={"idle_rate": 0.5}).status_code == 400
    assert client.put("/api/settings", json={"detect_jump_frac": 0.01}).status_code == 400
    assert client.put("/api/settings", json={"overstock_frac": "x"}).json()["error"]["code"] == "BAD_PARAMS"
    r = client.put("/api/settings", json={"overstock_frac": 0.5})
    assert r.status_code == 200 and r.json()["overstock_frac"] == 0.5
    assert client.get("/api/settings").json()["overstock_frac"] == 0.5
    assert client.get("/api/settings").json()["idle_rate"] == g["idle_rate"]  # partial update
    assert client.get(f"/api/fleet?{Q}").json()["pending_tids"] == []


def test_responses_deterministic(client):
    _warm(client)

    def body():
        b = client.get(f"/api/fleet?{Q}").json()
        b.pop("job_id")
        return b

    assert body() == body()
    a = client.get(f"/api/atm/TID-JKT-0001?{Q}")
    b = client.get(f"/api/atm/TID-JKT-0001?{Q}")
    assert a.content.replace(b'"job_id":null', b"") == b.content.replace(b'"job_id":null', b"")
