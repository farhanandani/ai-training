"""Shared API test fixtures: TestClient, thread-mode runner, fast fake forecasts (no real model fits)."""

import pytest
from fastapi.testclient import TestClient
from test_services import _fast_run_tid

import engine.forecast as F
from app.main import create_app
from app.settings import Settings


@pytest.fixture
def client(tmp_path, seed_dir, monkeypatch):
    monkeypatch.setattr(F, "run_tid", _fast_run_tid)
    s = Settings(workspace_db=tmp_path / "ws" / "workspace.db", seed_dir=seed_dir, workers=2)
    app = create_app(s, start_warmup=False, runner_mode="thread")
    with TestClient(app) as c:
        yield c
