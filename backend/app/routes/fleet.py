"""/api/fleet."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.dto import FleetResponse
from app.routes.deps import ViewParams, get_services, view_params
from app.services import Services

router = APIRouter()


@router.get("/fleet", response_model=FleetResponse)
def fleet(p: Annotated[ViewParams, Depends(view_params)], svc: Annotated[Services, Depends(get_services)]):
    return svc.fleet(p.as_of, p.h, p.sl)
