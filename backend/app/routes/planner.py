"""/api/plan: allocation, manual overrides, CSV export (TR-36, PRD 6.3-6.5)."""

from __future__ import annotations

import csv
import io
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import Response

from app.dto import OkResponse, OverridesRequest, PlanRequest, PlanResponse
from app.errors import ApiError
from app.routes.deps import ViewParams, get_services, view_params
from app.services import Services
from engine.schema import Override

router = APIRouter()


@router.post("/plan", response_model=PlanResponse)
def plan(body: PlanRequest, svc: Annotated[Services, Depends(get_services)]):
    svc.validate_as_of(body.as_of)
    out = svc.plan(body.as_of, body.h, body.sl, body.budget)  # raises BAD_PARAMS on a negative budget
    for k, v in (("h", body.h), ("sl", body.sl), ("budget", body.budget)):
        svc.store.set_setting(k, v)
    return out


@router.put("/plan/overrides", response_model=OkResponse)
def put_overrides(body: OverridesRequest, svc: Annotated[Services, Depends(get_services)]):
    known = {m.tid for m in svc.store.get_master()}
    for o in body.overrides:
        if o.tid not in known:
            raise ApiError(404, "UNKNOWN_TID", f"unknown TID {o.tid}", {"tid": o.tid})
    svc.store.put_overrides(
        [Override(o.tid, o.visit_date, o.amount, o.skipped, o.moved_from) for o in body.overrides]
    )
    return {"ok": True}


@router.delete("/plan/overrides", response_model=OkResponse)
def delete_overrides(svc: Annotated[Services, Depends(get_services)]):
    svc.store.clear_overrides()
    return {"ok": True}


@router.get("/plan/export.csv")
def export_csv(
    p: Annotated[ViewParams, Depends(view_params)], svc: Annotated[Services, Depends(get_services)]
):
    budget = svc.store.get_setting("budget")
    out = svc.plan(p.as_of, p.h, p.sl, budget)
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["tid", "visit_date", "amount", "source"])
    for v in out["visits"]:  # already sorted by (tid, date)
        if "skip" in v["flags"]:
            continue
        source = "manual" if v["manual"] else "extra" if v["kind"] == "extra" else "recommended"
        w.writerow([v["tid"], v["date"], v["allocated"], source])
    return Response(
        buf.getvalue(),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="replenishment-plan-{p.as_of.isoformat()}.csv"'
        },
    )
