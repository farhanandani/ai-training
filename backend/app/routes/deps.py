"""Shared route dependencies: the Services handle and the as_of/h/sl query params (TR-35 validation)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Annotated

from fastapi import Depends, Query, Request

from app.dto import SL
from app.services import Services


def get_services(request: Request) -> Services:
    return request.app.state.services


@dataclass
class ViewParams:
    as_of: date
    h: int
    sl: str


def view_params(
    svc: Annotated[Services, Depends(get_services)],
    as_of: Annotated[date | None, Query()] = None,
    h: Annotated[int | None, Query(ge=7, le=30)] = None,
    sl: Annotated[SL | None, Query()] = None,
) -> ViewParams:
    as_of = as_of or svc.current_as_of()
    svc.validate_as_of(as_of)
    return ViewParams(as_of, h or int(svc._biz("h")), sl or svc._biz("sl"))
