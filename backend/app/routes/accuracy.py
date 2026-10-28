"""/api/accuracy."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.dto import AccuracyResponse
from app.routes.deps import ViewParams, get_services, view_params
from app.services import Services

router = APIRouter()


@router.get("/accuracy", response_model=AccuracyResponse)
def accuracy(p: Annotated[ViewParams, Depends(view_params)], svc: Annotated[Services, Depends(get_services)]):
    return svc.accuracy(p.as_of, p.h)
