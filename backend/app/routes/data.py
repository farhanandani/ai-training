"""/api/data: grid read + edits, master/holidays, upload, validation, download, reset (ARCHITECTURE 8, TR-37)."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

import pandas as pd
from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import Response

from app import data_service as ds
from app.dto import (
    HolidayRows,
    LogDeleteRequest,
    LogPage,
    LogPatchRequest,
    LogPostRequest,
    MasterRows,
    ValidationResponse,
    WriteResponse,
)
from app.errors import ApiError
from app.routes.deps import get_services
from app.services import Services
from engine.schema import AtmMaster

router = APIRouter(prefix="/data")
Svc = Annotated[Services, Depends(get_services)]
Kind = Literal["log", "master", "holidays"]


@router.get("/log", response_model=LogPage)
def get_log(
    svc: Svc,
    tid: Annotated[str | None, Query()] = None,
    from_: Annotated[date | None, Query(alias="from")] = None,
    to: Annotated[date | None, Query()] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=1000)] = 200,
):
    df = svc.store.get_log([tid] if tid else None, from_, to)  # sorted by tid, date
    part = df.iloc[(page - 1) * page_size : page * page_size]
    return {"rows": part.to_dict("records"), "total": len(df)}


@router.patch("/log", response_model=WriteResponse)
def patch_log(body: LogPatchRequest, svc: Svc):
    return ds.patch_log(svc, [r.model_dump() for r in body.rows])


@router.post("/log", response_model=WriteResponse)
def post_log(body: LogPostRequest, svc: Svc):
    return ds.post_log(svc, [r.model_dump() for r in body.rows])


@router.delete("/log", response_model=WriteResponse)
def delete_log(body: LogDeleteRequest, svc: Svc):
    return ds.delete_log(svc, [(k.tid, k.date) for k in body.keys])


@router.get("/master", response_model=MasterRows)
def get_master(svc: Svc):
    return {"rows": [m.__dict__ for m in svc.store.get_master()]}


@router.put("/master", response_model=WriteResponse)
def put_master(body: MasterRows, svc: Svc):
    return ds.put_master(svc, [AtmMaster(**r.model_dump()) for r in body.rows])


@router.get("/holidays", response_model=HolidayRows)
def get_holidays(svc: Svc):
    return {"rows": svc.store.get_holidays().to_dict("records")}


@router.put("/holidays", response_model=WriteResponse)
def put_holidays(body: HolidayRows, svc: Svc):
    df = pd.DataFrame([r.model_dump() for r in body.rows], columns=["date", "name", "type"])
    return ds.put_holidays(svc, df)


@router.post("/upload", response_model=WriteResponse)
def upload(
    svc: Svc,
    file: Annotated[UploadFile, File()],
    kind: Annotated[Kind, Form()],
    mode: Annotated[Literal["replace", "merge"], Form()] = "merge",
):
    limit = int(svc.settings.max_upload_mb * 1024 * 1024)
    data = file.file.read(limit + 1)  # size check before parsing (TR-07); sync route runs in the threadpool
    if len(data) > limit:
        raise ApiError(
            413,
            "FILE_TOO_LARGE",
            f"file is larger than {svc.settings.max_upload_mb} MB",
            {"max_upload_mb": svc.settings.max_upload_mb},
        )
    return ds.upload(svc, data, file.filename or "upload.csv", kind, mode)


@router.get("/validation", response_model=ValidationResponse)
def validation(svc: Svc):
    return {"issues": [ds.issue_dict(i) for i in svc.store.get_issues()]}  # stored, not re-run (TR-14)


@router.get("/download")
def download(kind: Annotated[Kind, Query()], svc: Svc):
    return Response(
        ds.download_csv(svc, kind),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{ds.DOWNLOAD_NAMES[kind]}"'},
    )


@router.post("/reset", response_model=WriteResponse)
def reset(svc: Svc):
    return ds.reset(svc)
