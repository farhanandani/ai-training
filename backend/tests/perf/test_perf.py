"""TR-39 timing checks with the REAL process-pool worker on a fresh seeded workspace. Run: pytest -m perf -s."""

import time

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Settings

pytestmark = pytest.mark.perf

AS_OF = "2026-03-06"
Q = f"as_of={AS_OF}&h=21&sl=p90"
TID = "TID-JKT-0001"


@pytest.fixture(scope="module")
def warm(tmp_path_factory, request):
    """Fresh workspace, real workers; the cold forecast of all 10 TIDs is timed once here."""
    seed = request.config.rootpath.parent / "data"
    s = Settings(workspace_db=tmp_path_factory.mktemp("perf") / "workspace.db", seed_dir=seed)
    with TestClient(create_app(s, start_warmup=False)) as client:
        t0 = time.perf_counter()
        body = client.get(f"/api/fleet?{Q}").json()
        assert len(body["pending_tids"]) == 10
        assert client.app.state.services.runner.wait(body["job_id"], timeout=300)
        cold = time.perf_counter() - t0
        print(f"\ncold forecast, 10 TIDs @ {AS_OF}, workers={s.workers}: {cold:.1f} s")
        yield client, cold, seed


def test_cold_forecast_all_tids(warm):
    client, cold, _ = warm
    body = client.get(f"/api/fleet?{Q}").json()
    assert body["pending_tids"] == []
    assert all(a["status"] != "forecast_failed" for a in body["atms"])
    assert cold <= 60.0


def _best_of(client, url, n=3):
    times = []
    for _ in range(n):
        t0 = time.perf_counter()
        r = client.get(url)
        times.append(time.perf_counter() - t0)
        assert r.status_code == 200
    return min(times), max(times)


def test_warm_fleet_and_atm_latency(warm):
    client, _, _ = warm
    client.get(f"/api/fleet?{Q}")  # first warm call
    fleet = _best_of(client, f"/api/fleet?{Q}")
    atm = _best_of(client, f"/api/atm/{TID}?{Q}")
    print(f"\nGET /api/fleet warm: {fleet[0] * 1000:.0f}-{fleet[1] * 1000:.0f} ms")
    print(f"GET /api/atm/{TID} warm: {atm[0] * 1000:.0f}-{atm[1] * 1000:.0f} ms")
    assert fleet[1] <= 0.300
    assert atm[1] <= 0.300


def test_upload_full_dummy_log(warm):
    """Parse + validate + store of 10 TIDs x 2 years; the forecast is only submitted (async), never awaited."""
    client, _, seed = warm
    data = (seed / "atm_daily_log.csv").read_bytes()
    t0 = time.perf_counter()
    r = client.post(
        "/api/data/upload",
        files={"file": ("atm_daily_log.csv", data, "text/csv")},
        data={"kind": "log", "mode": "replace"},
    )
    elapsed = time.perf_counter() - t0
    print(f"\nupload full dummy log (replace): {elapsed:.2f} s")
    assert r.status_code == 200
    assert elapsed <= 3.0
