"""FastAPI app factory (ARCHITECTURE 8). The SPA is mounted in a later task."""

from __future__ import annotations

import threading
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.errors import ApiError
from app.jobs import JobRunner

# from app.routes import accuracy, atm, fleet, planner, system
from app.routes import accuracy, atm, data, fleet, planner, system
from app.services import Services
from app.settings import Settings
from app.store import Store


def _error(status: int, code: str, message: str, details: dict | None = None) -> JSONResponse:
    return JSONResponse(ApiError(status, code, message, details).to_dict(), status_code=status)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, e: ApiError):
        return _error(e.status, e.code, e.message, e.details)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, e: RequestValidationError):
        errs = e.errors()
        first = errs[0] if errs else {}
        loc = ".".join(str(x) for x in first.get("loc", ()) if x not in ("query", "body", "path"))
        message = (
            f"invalid parameter {loc}: {first.get('msg', 'invalid value')}" if loc else "invalid request"
        )
        fields = [{"loc": [str(x) for x in er.get("loc", ())], "msg": er.get("msg", "")} for er in errs]
        return _error(400, "BAD_PARAMS", message, {"errors": fields})


def create_app(
    settings: Settings | None = None,
    start_warmup: bool = True,
    runner_mode: Literal["process", "thread"] = "process",
) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        store = Store(settings.workspace_db, settings.seed_dir)
        runner = JobRunner(settings.workers, mode=runner_mode)
        svc = Services(store, runner, settings)
        app.state.store, app.state.runner, app.state.services = store, runner, svc
        if start_warmup and settings.warmup_scenarios:
            threading.Thread(target=svc.warmup, daemon=True, name="warmup").start()
        try:
            yield
        finally:
            runner.shutdown()
            store.close()

    app = FastAPI(title="ATM Cash Forecasting", lifespan=lifespan)
    install_error_handlers(app)
    # for mod in (system, fleet, atm, accuracy):
    # for mod in (system, fleet, atm, accuracy, planner):
    for mod in (system, fleet, atm, accuracy, planner, data):
        app.include_router(mod.router, prefix="/api")
    return app
