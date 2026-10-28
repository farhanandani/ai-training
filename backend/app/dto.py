"""Pydantic response/request models for the read API (source for the generated frontend types)."""

from __future__ import annotations

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
