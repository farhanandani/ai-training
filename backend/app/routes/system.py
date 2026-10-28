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
    # lo, hi = svc._as_of_range()
    log = svc.store.get_log()
    lo, hi = svc._as_of_range() if not log.empty else (None, None)  # F5: empty log -> no range, no 409
    iso = lambda d: d.isoformat() if d is not None else None
    return {
        "data_source": svc.store.source_label(),
        # "min_date": log["date"].min().isoformat(),
        # "max_date": log["date"].max().isoformat(),
        # "as_of_min": lo.isoformat(),
        # "as_of_max": hi.isoformat(),
        "min_date": iso(log["date"].min()) if not log.empty else None,
        "max_date": iso(log["date"].max()) if not log.empty else None,
        "as_of_min": iso(lo),
        "as_of_max": iso(hi),
        "tids": sorted(m.tid for m in svc.store.get_master()),
        "scenarios": [
            # {"id": sid, "label": SCENARIO_LABELS[sid], "as_of": (d or hi).isoformat(), "h": h}
            {
                "id": sid,
                "label": SCENARIO_LABELS[sid],
                "as_of": iso(d or hi),
                "h": h,
                "in_range": lo is not None and lo <= (d or hi) <= hi,
            }
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
