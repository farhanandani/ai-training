"""/api/atm/{tid}."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.dto import AtmResponse
from app.routes.deps import ViewParams, get_services, view_params
from app.services import Services

router = APIRouter()


@router.get("/atm/{tid}", response_model=AtmResponse)
def atm(
    tid: str,
    p: Annotated[ViewParams, Depends(view_params)],
    svc: Annotated[Services, Depends(get_services)],
    from_: Annotated[date | None, Query(alias="from")] = None,
):
    return svc.atm(tid, p.as_of, p.h, p.sl, from_)
