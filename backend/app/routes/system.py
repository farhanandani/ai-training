"""/api/context, /api/settings, /api/status."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.dto import ContextResponse, SettingsResponse, SettingsUpdate, StatusResponse
from app.errors import ApiError
from app.routes.deps import get_services
from app.services import DEFAULT_SCENARIO, SCENARIO_LABELS, SCENARIOS, Services

router = APIRouter()
SETTING_KEYS = ("h", "sl", "budget", "overstock_frac", "idle_rate", "detect_jump_frac")


def _settings(svc: Services) -> dict:
    return {k: svc._biz(k) for k in SETTING_KEYS}


@router.get("/context", response_model=ContextResponse)
def context(svc: Annotated[Services, Depends(get_services)]):
    lo, hi = svc._as_of_range()
    log = svc.store.get_log()
    return {
        "data_source": svc.store.source_label(),
        "min_date": log["date"].min().isoformat(),
        "max_date": log["date"].max().isoformat(),
        "as_of_min": lo.isoformat(),
        "as_of_max": hi.isoformat(),
        "tids": sorted(m.tid for m in svc.store.get_master()),
        "scenarios": [
            {"id": sid, "label": SCENARIO_LABELS[sid], "as_of": (d or hi).isoformat(), "h": h}
            for sid, (d, h) in SCENARIOS.items()
        ],
        "default_scenario": DEFAULT_SCENARIO,
        "defaults": _settings(svc),
        "dataset_version": svc.store.dataset_version(),
    }


@router.get("/settings", response_model=SettingsResponse)
def get_settings(svc: Annotated[Services, Depends(get_services)]):
    return _settings(svc)


@router.put("/settings", response_model=SettingsResponse)
def put_settings(body: SettingsUpdate, svc: Annotated[Services, Depends(get_services)]):
    # light-layer values only: services read them on every call, so no forecast key changes (no refit)
    for k, v in body.model_dump(exclude_none=True).items():
        svc.store.set_setting(k, v)
    return _settings(svc)


@router.get("/status", response_model=StatusResponse)
def status(job_id: Annotated[str, Query()], svc: Annotated[Services, Depends(get_services)]):
    st = svc.runner.status(job_id)
    if st is None:
        raise ApiError(404, "UNKNOWN_JOB", f"unknown or expired job {job_id}", {"job_id": job_id})
    return st
