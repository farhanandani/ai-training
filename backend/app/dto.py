"""Pydantic response/request models for the read API (source for the generated frontend types)."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field

SL = Literal["p50", "p80", "p90", "p95"]


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    error: ErrorBody


# ------------------------------------------------------------------ context
class ScenarioDto(BaseModel):
    id: str
    label: str
    as_of: str
    h: int


class BusinessDefaults(BaseModel):
    h: int
    sl: SL
    budget: int | None
    overstock_frac: float
    idle_rate: float
    detect_jump_frac: float


class ContextResponse(BaseModel):
    data_source: str
    min_date: str
    max_date: str
    as_of_min: str
    as_of_max: str
    tids: list[str]
    scenarios: list[ScenarioDto]
    default_scenario: str
    defaults: BusinessDefaults
    dataset_version: int


# ----------------------------------------------------------------- settings
class SettingsResponse(BusinessDefaults):
    pass


class SettingsUpdate(BaseModel):
    """Partial body; ranges per TR-06."""

    overstock_frac: float | None = Field(default=None, ge=0.10, le=0.90)
    idle_rate: float | None = Field(default=None, ge=0.0, le=0.30)
    detect_jump_frac: float | None = Field(default=None, ge=0.05, le=0.80)


# -------------------------------------------------------------------- fleet
class Kpis(BaseModel):
    at_risk: int
    over_stocked: int
    idle_cash: int
    recommended_total: int


class FleetAtm(BaseModel):
    tid: str
    location_name: str
    location_type: str
    balance: int
    capacity: int
    days_of_cash: int | None
    status: str
    next_visit: str | None
    recommended_amount: int | None
    inferred_master: bool
    error: str | None = None


class FleetResponse(BaseModel):
    as_of: str
    h: int
    sl: SL
    dataset_version: int
    pending_tids: list[str]
    job_id: str | None
    kpis: Kpis
    atms: list[FleetAtm]


# ---------------------------------------------------------------------- atm
class MasterDto(BaseModel):
    tid: str
    location_name: str
    location_type: str
    capacity: int
    min_safe_balance: int
    replenish_cycle_days: int
    denomination: int
    cost_per_visit: int
    current_fill_level: int
    next_visit_date: str | None = None
    inferred: bool = False


class HistoryPoint(BaseModel):
    date: str
    withdrawal: int
    closing_balance: int
    replenishment: int


class ForecastPoint(BaseModel):
    date: str
    q10: int
    q50: int
    q80: int
    q90: int
    q95: int


class ActualPoint(BaseModel):
    date: str
    withdrawal: int


class CurrentProjPoint(BaseModel):
    date: str
    p50: int
    p90: int


class RecommendedProjPoint(BaseModel):
    date: str
    p50: int
    sl: int


class Projection(BaseModel):
    current: list[CurrentProjPoint]
    recommended: list[RecommendedProjPoint]


class VisitDto(BaseModel):
    date: str
    kind: str
    amount: int
    tier1_need: int
    reason: str
    flags: list[str]
    manual: bool


class ModelInfo(BaseModel):
    name: str
    fallback: bool
    orders: Any | None = None
    backtest_stale: bool = False


class MetricsDto(BaseModel):
    wape: float | None
    mape: float | None
    mae: int | None
    coverage: float | None
    n: int


class HolidayDto(BaseModel):
    date: str
    name: str
    type: str


class AtmResponse(BaseModel):
    tid: str
    master: MasterDto
    status: str
    days_of_cash: int | None
    history: list[HistoryPoint]
    forecast: list[ForecastPoint]
    actual_after: list[ActualPoint] | None
    projection: Projection
    visits: list[VisitDto]
    explanations: dict[str, list[str]]
    model: ModelInfo | None
    metrics: MetricsDto | None
    holidays_in_view: list[HolidayDto]
    pending: bool
    job_id: str | None
    error: str | None


# ----------------------------------------------------------------- accuracy
class CandidateMetrics(MetricsDto):
    model: str


class LebaranCheck(BaseModel):
    origin: str
    fitri_day: str
    metrics: MetricsDto | None


class BacktestPoint(BaseModel):
    origin: str
    date: str
    y: int | None
    q10: int | None
    q50: int | None
    q90: int | None


class AccuracyAtm(BaseModel):
    tid: str
    status: str
    model: str | None
    fallback: bool
    backtest_stale: bool = False
    error: str | None
    metrics: MetricsDto | None
    candidates: list[CandidateMetrics]
    lebaran_check: LebaranCheck | None
    backtest: list[BacktestPoint]


class AccuracyResponse(BaseModel):
    as_of: str
    h: int
    dataset_version: int
    pending_tids: list[str]
    job_id: str | None
    atms: list[AccuracyAtm]


# ------------------------------------------------------------------- status
class FailedTid(BaseModel):
    tid: str
    error: str


class StatusResponse(BaseModel):
    job_id: str
    done: bool
    total: int
    finished: int
    failed: list[FailedTid]


# ------------------------------------------------------------------ planner
class PlanRequest(BaseModel):
    as_of: date
    h: int = Field(ge=7, le=30)
    sl: SL
    budget: int | None = Field(default=None, ge=0)
    persist: bool = True  # F4: save h/sl/budget as settings (the planner's base query sends false)


class OverrideDto(BaseModel):
    tid: str
    visit_date: date
    amount: int | None = Field(default=None, ge=0)
    skipped: bool = False
    moved_from: date | None = None


class OverridesRequest(BaseModel):
    # the complete desired override set for the plan window (as_of, as_of + h]; it replaces the stored one
    as_of: date
    h: int = Field(ge=7, le=30)
    overrides: list[OverrideDto]


class OkResponse(BaseModel):
    ok: bool = True


class PlanOverrideInfo(BaseModel):
    amount: int | None
    skipped: bool
    moved_from: str | None


class PlanVisit(BaseModel):
    tid: str
    date: str
    kind: str
    recommended: int
    allocated: int
    override: PlanOverrideInfo | None
    tier1_need: int
    reason: str
    flags: list[str]
    manual: bool


class PlanResponse(BaseModel):
    as_of: str
    h: int
    sl: SL
    budget: int | None
    dataset_version: int
    pending_tids: list[str]
    job_id: str | None
    need_total: int
    funded_total: int
    funded_pct: float
    unused: int
    underfunded: int
    visits: list[PlanVisit]
    reallocation: list[Any]
    comparison: dict[str, Any]


# --------------------------------------------------------------------- data
HolidayType = Literal["new_year", "christmas", "idul_fitri", "cuti_bersama", "national"]


class IssueDto(BaseModel):
    severity: Literal["error", "warning", "info"]
    code: str
    message: str
    tid: str | None = None
    date: str | None = None


class JobRef(BaseModel):
    job_id: str | None
    pending_tids: list[str]


class WriteResponse(BaseModel):
    """TR-37 body of every data write."""

    dataset_version: int
    issues: list[IssueDto]
    job: JobRef


class ValidationResponse(BaseModel):
    issues: list[IssueDto]


class LogRow(BaseModel):
    tid: str
    date: date
    opening_balance: int
    withdrawal: int
    replenishment: int
    closing_balance: int
    source: str


class LogPage(BaseModel):
    rows: list[LogRow]
    total: int


class LogRowIn(BaseModel):
    tid: str = Field(min_length=1)
    date: date
    opening_balance: int = Field(ge=0)
    withdrawal: int = Field(ge=0)
    replenishment: int = Field(ge=0)
    closing_balance: int = Field(ge=0)


class LogRowPatch(BaseModel):
    """TR-37: fields not given keep their stored values."""

    tid: str
    date: date
    opening_balance: int | None = Field(default=None, ge=0)
    withdrawal: int | None = Field(default=None, ge=0)
    replenishment: int | None = Field(default=None, ge=0)
    closing_balance: int | None = Field(default=None, ge=0)


class LogPatchRequest(BaseModel):
    rows: list[LogRowPatch] = Field(min_length=1)


class LogPostRequest(BaseModel):
    rows: list[LogRowIn] = Field(min_length=1)


class LogKey(BaseModel):
    tid: str
    date: date


class LogDeleteRequest(BaseModel):
    keys: list[LogKey] = Field(min_length=1)


class MasterRow(BaseModel):
    tid: str = Field(min_length=1)
    location_name: str
    location_type: str
    capacity: int = Field(ge=0)
    min_safe_balance: int = Field(ge=0)
    replenish_cycle_days: int = Field(ge=1, le=31)
    denomination: Literal[50000, 100000]
    cost_per_visit: int = Field(ge=0)
    current_fill_level: int = Field(ge=0)
    next_visit_date: date | None = None
    inferred: bool = False


class MasterRows(BaseModel):
    rows: list[MasterRow]


class HolidayRow(BaseModel):
    date: date
    name: str
    type: HolidayType


class HolidayRows(BaseModel):
    rows: list[HolidayRow]
