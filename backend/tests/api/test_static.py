"""Static SPA serving (Task 16): API stays reachable, unknown non-API paths fall back to index.html."""

import pytest
from fastapi.testclient import TestClient
from test_services import _fast_run_tid

import engine.forecast as F
from app.main import create_app
from app.settings import Settings


def _client(tmp_path, seed_dir, dist):
    s = Settings(
        workspace_db=tmp_path / "ws" / "workspace.db", seed_dir=seed_dir, workers=2, frontend_dist=dist
    )
    return TestClient(create_app(s, start_warmup=False, runner_mode="thread"))


@pytest.fixture
def dist(tmp_path):
    d = tmp_path / "dist"
    (d / "assets").mkdir(parents=True)
    (d / "index.html").write_text("<html><body>SPA-INDEX</body></html>", encoding="utf-8")
    (d / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    return d


def test_api_still_works_with_dist(tmp_path, seed_dir, dist, monkeypatch):
    monkeypatch.setattr(F, "run_tid", _fast_run_tid)
    with _client(tmp_path, seed_dir, dist) as c:
        r = c.get("/api/context")
        assert r.status_code == 200 and "scenarios" in r.json()
        assert c.get("/openapi.json").status_code == 200
        assert "swagger" in c.get("/docs").text.lower()


def test_root_and_spa_fallback_serve_index(tmp_path, seed_dir, dist, monkeypatch):
    monkeypatch.setattr(F, "run_tid", _fast_run_tid)
    with _client(tmp_path, seed_dir, dist) as c:
        assert "SPA-INDEX" in c.get("/").text
        r = c.get("/atm/1001")
        assert r.status_code == 200 and "SPA-INDEX" in r.text
        assert c.get("/assets/app.js").text == "console.log(1)"


def test_unknown_api_path_is_not_index(tmp_path, seed_dir, dist, monkeypatch):
    monkeypatch.setattr(F, "run_tid", _fast_run_tid)
    with _client(tmp_path, seed_dir, dist) as c:
        r = c.get("/api/nope")
        assert r.status_code == 404 and "SPA-INDEX" not in r.text
        assert r.json()["error"]["code"] == "NOT_FOUND"
        r = c.post("/api/nope", json={})
        assert r.status_code == 404 and r.json()["error"]["code"] == "NOT_FOUND"


def test_no_dist_api_still_starts(tmp_path, seed_dir, monkeypatch):
    monkeypatch.setattr(F, "run_tid", _fast_run_tid)
    with _client(tmp_path, seed_dir, tmp_path / "missing") as c:
        assert c.get("/api/context").status_code == 200
        assert c.get("/").status_code == 404


def test_cors_only_in_dev(tmp_path, seed_dir, dist, monkeypatch):
    monkeypatch.setattr(F, "run_tid", _fast_run_tid)
    hdr = {"Origin": "http://localhost:5173"}
    monkeypatch.delenv("CASHFC_DEV", raising=False)
    with _client(tmp_path, seed_dir, dist) as c:
        assert "access-control-allow-origin" not in c.get("/api/context", headers=hdr).headers
    monkeypatch.setenv("CASHFC_DEV", "1")
    with _client(tmp_path, seed_dir, dist) as c:
        assert c.get("/api/context", headers=hdr).headers["access-control-allow-origin"] == hdr["Origin"]
        other = c.get("/api/context", headers={"Origin": "http://evil.example"})
        assert "access-control-allow-origin" not in other.headers
