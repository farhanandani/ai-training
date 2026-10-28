# ATM Cash Forecasting Demo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A local web demo that forecasts daily ATM withdrawals per TID and recommends when and how much to refill, allocating a limited budget across ATMs, on dummy or uploaded daily balance logs.

**Architecture:** A pure-Python `engine/` package does the work. It has a heavy layer (fit, backtest and forecast per TID, run in a process pool and cached in SQLite) and a light layer (schedule, plan, allocate and compare, run on every request). `app/` is a thin FastAPI layer over it, which also serves the built React SPA from one process on 127.0.0.1:8000.

**Tech Stack:** Python 3.13, pandas, numpy, statsmodels, FastAPI, SQLite. React 18, Vite, TypeScript, TanStack Query, Zustand, ECharts, AG Grid Community, Tailwind. Tests: pytest, Vitest, Playwright.

**Spec:** `docs/PRD.md` (business rules, AC1–AC10), `docs/ARCHITECTURE.md` (structure and flows), `docs/TRD.md` (exact parameters, `TR-01`…`TR-46`). Read all three before starting a task. When this plan cites a section, the cited text is the requirement.

## Global Constraints

- Python 3.13 in `backend/.venv` only. Never install into global site-packages (TR-01). Activate it with `backend\.venv\Scripts\Activate.ps1`.
- Dependency floors are listed in TR-02 (backend) and TR-03 (frontend). No other runtime dependencies without a stated reason.
- No CDN or remote fonts at runtime. The demo must work offline after install (TR-04).
- `engine/` never imports `app/`. Engine functions do no file or DB I/O and use no globals (ARCHITECTURE §2).
- Money is `int` IDR everywhere outside model internals. Amounts are rounded to `denomination` and capped at `capacity` (TR-30).
- `true_demand` is read only by `engine/compare.py` (via `app/services.py`). Forecasting code must never touch it (TR-16).
- The only balance simulator is `engine.plan.simulate_balance`. Daily order: load in the morning → withdraw → close (TR-19).
- Forecasts are always 30 days. The horizon `h` (7–30) only slices, and never refits (ARCHITECTURE §4.2).
- The UI copy is English. Format money with `Intl.NumberFormat('id-ID')` as `Rp 640.000.000`, compact `Rp 640 jt` / `Rp 1,2 M`, and dates as `12 Mar 2026` (PRD §7).
- The server binds to 127.0.0.1 only. CORS is on only in dev, for `http://localhost:5173` (TR-42).
- **Owner rule (CLAUDE.md):** when changing or replacing an existing line of code, keep the old line as a comment directly above the new one. Bug fixes too.
- Done means `ruff check`, `ruff format --check`, `pytest -m "not perf"`, and (from Task 16 on) `npm run lint`, `npm run build`, `npx vitest run` all pass (TR-46).

## Review Focus

1. **Indonesian-formatted numbers in an upload** (`1.000.000`, `;` delimiter, `Rp` prefix). The expected result is row-level `BAD_AMOUNT` issues and the rest of the file stored, never a 500 error. Covered in Task 2 (`test_id_thousand_separator_is_row_error`) and Task 15 (`test_upload_semicolon_rp_prefix`).
2. **A newly uploaded TID with less than 280 days of history.** The expected result is status `insufficient_history` on Fleet and Planner, the other TIDs unaffected, and no crash. Covered in Task 6 (`test_short_history_returns_none`), Task 8 (`test_insufficient_history_plan`), and Task 13 (`test_fleet_with_short_history_tid`).
3. **A budget of 0, or a budget larger than the need.** Budget 0 means everything is underfunded, all allocations are 0, and nothing goes negative. A budget above the need is fully funded, with the unused amount reported. Covered in Task 9 (`test_zero_budget`, `test_budget_above_need`).
4. **A master edited so that `capacity` is below the current balance, or `current_fill_level` is above `capacity`.** Loads are clamped to ≥ 0 and the plan still renders. Covered in Task 8 (`test_capacity_below_balance_never_negative_load`).
5. **A holiday table that does not cover `as_of + 30`.** That TID's forecast fails with a clear `HOLIDAYS_NOT_COVERED` message, shown per TID, and the API does not return a 500. Covered in Task 3 (`test_features_raise_when_holidays_short`) and Task 12 (`test_job_records_holiday_coverage_failure`).

---

## File map

```
backend/pyproject.toml                 deps, ruff, pytest markers (perf, slow)
backend/engine/__init__.py             ENGINE_VERSION
backend/engine/schema.py               dataclasses + column constants
backend/engine/ingest.py               read_table, aliases, parsing, aggregation, derivation
backend/engine/validate.py             validate_log, infer_master
backend/engine/preprocess.py           demand_series
backend/engine/calendar.py             features, fitri_days
backend/engine/models/{base,seasonal_naive,ets,sarimax}.py
backend/engine/backtest.py             origins, run_backtest, metrics
backend/engine/forecast.py             run_tid, explanations, payload (de)serialization
backend/engine/schedule.py             scheduled_visits
backend/engine/plan.py                 simulate_balance, project_current, recommend
backend/engine/allocate.py             allocate, reallocation_flows
backend/engine/compare.py              policy_stats, compare
backend/app/{main,settings,store,jobs,services,dto,errors}.py
backend/app/routes/{system,fleet,atm,planner,data,accuracy}.py
backend/tests/conftest.py              seed_dir, dummy frames, temp workspace fixtures
frontend/…                             Vite app (Tasks 16–19)
scripts/run.ps1, scripts/dev.ps1
e2e/ (Playwright, in frontend/tests/e2e)
```

---

### Task 1: Repo bootstrap, venv, generator test

**Files:**
- Create: `.gitignore`, `backend/pyproject.toml`, `backend/engine/__init__.py`, `backend/app/__init__.py`, `backend/tests/conftest.py`, `backend/tests/engine/test_generator.py`

**Interfaces:**
- Produces: the pytest fixture `seed_dir() -> Path` (repo `data/`); `engine.ENGINE_VERSION: str = "1"`; pytest markers `perf` and `slow`.

- [ ] **Step 1:** Run `git init` in `D:\Training`. In `.gitignore`, ignore `backend/.venv/`, `workspace/`, `frontend/node_modules/`, `frontend/dist/`, `__pycache__/`, `*.egg-info/`, `.pytest_cache/`, `test-results/`.
- [ ] **Step 2:** Write `backend/pyproject.toml`:
  - Project `cashfc`, `requires-python = ">=3.13"`, runtime deps from TR-02, and the `dev` extra (pytest, httpx, ruff).
  - Packages `engine*` and `app*`.
  - `[tool.pytest.ini_options]` with `markers = ["perf: timing tests, run manually", "slow: golden model tests"]` and `testpaths = ["tests"]`.
  - `[tool.ruff] line-length = 110`.
- [ ] **Step 3:** Create the venv and install per TR-01. Run `pip freeze > requirements.lock`.
  Expected: `python -c "import statsmodels, fastapi; print('ok')"` prints `ok`.
- [ ] **Step 4: Write the failing test** `tests/engine/test_generator.py`:

```python
def test_generator_reproducible_and_balanced(tmp_path, seed_dir):
    # copy generate_dummy.py into tmp_path, run it with subprocess (python -I), then:
    for name in ["atm_daily_log.csv", "atm_master.csv", "holidays_id.csv", "atm_true_demand.csv"]:
        assert sha256(tmp_path / name) == sha256(seed_dir / name)
    rows = list(csv.DictReader(open(tmp_path / "atm_daily_log.csv")))
    assert len(rows) == 7300
    assert all(int(r["opening_balance"]) - int(r["withdrawal"]) + int(r["replenishment"])
               == int(r["closing_balance"]) for r in rows)
```

- [ ] **Step 5:** Run `pytest tests/engine/test_generator.py -v`. It fails at first only because the `seed_dir` fixture is missing. Add `seed_dir` to `conftest.py` (`Path(__file__).resolve().parents[2] / "data"`) and run again. Expected: PASS.
- [ ] **Step 6:** Run `ruff check . && ruff format --check .`. Expected: clean.
- [ ] **Step 7:** Commit with `git add -A` and the message `chore: bootstrap backend package, venv deps, generator reproducibility test`.

---

### Task 2: Schema and ingest

**Files:**
- Create: `backend/engine/schema.py`, `backend/engine/ingest.py`
- Test: `backend/tests/engine/test_ingest.py`

**Interfaces:**
- Produces (`schema.py`):
  - `LOG_COLS = ["tid","date","opening_balance","withdrawal","replenishment","closing_balance"]`
  - `@dataclass(frozen=True) class Issue: severity: Literal["error","warning","info"]; code: str; message: str; tid: str | None = None; date: date | None = None`
  - `@dataclass class AtmMaster` with fields: `tid, location_name, location_type, capacity, min_safe_balance, replenish_cycle_days, denomination, cost_per_visit, current_fill_level, next_visit_date: date | None = None, inferred: bool = False`
  - `@dataclass(frozen=True) class Override: tid: str; visit_date: date; amount: int | None; skipped: bool = False; moved_from: date | None = None`
- Produces (`ingest.py`):
  - `ALIASES: dict[str, str]`, from TR-08
  - `read_table(data: bytes, filename: str, kind: Literal["log","master","holidays"], detect_jump_frac: float = 0.20, capacities: dict[str,int] | None = None) -> tuple[pd.DataFrame, list[Issue]]`. It returns canonical columns, `date` as `datetime.date`, money as `int64`, a `source` column for logs (`"upload"` or `"derived"`), and drops invalid rows.
  - `class UnreadableFile(Exception)` with `.issues`, raised on encoding failure or a missing required column.

- [ ] **Step 1: Write failing tests**:
  - `test_csv_comma_and_semicolon_detected`: the same 3 rows, both delimiters → identical frames.
  - `test_alias_headers`: header `Terminal ID;Tanggal;Saldo Awal;Penarikan;Isi Ulang;Saldo Akhir` → columns equal `LOG_COLS` (+ `source`).
  - `test_date_formats`: `2026-03-01`, `01/03/2026` and `01-03-2026` all → `date(2026,3,1)`. `2026/03/01` → issue `BAD_DATE`, row dropped.
  - `test_rp_prefix_and_decimal`: `"Rp 1500000"` → 1500000 and `"1500000.6"` → 1500001.
  - `test_id_thousand_separator_is_row_error`: `"1.000.000"` → issue `BAD_AMOUNT` with `severity == "error"`; the other rows are kept.
  - `test_negative_amount_row_error`: → `NEGATIVE_VALUE`.
  - `test_duplicate_tid_date_aggregated`: two rows for the same day → one row with opening from the first row, closing from the last, sums of withdrawal and replenishment, and an `info` issue `DUPLICATE_KEY`.
  - `test_missing_required_column_raises`: no `closing_balance` → `UnreadableFile` with code `MISSING_COLUMN`.
  - `test_derive_withdrawal_and_replenishment`: a log without those two columns, capacity 1_000_000_000. Day 3 has closing − opening = +600 M (> 20% of cap), so it is a replenishment day, with the estimate = median of the same weekday over the prior 4 weeks (fall back to the median of all prior days if none). Other days: withdrawal = opening − closing. `source == "derived"`.
  - `test_xlsx_first_sheet`: an XLSX built with openpyxl in the test → same frame as the CSV.
  - `test_unknown_column_info`.
- [ ] **Step 2:** Run `pytest tests/engine/test_ingest.py -v`. Expected: FAIL (module missing).
- [ ] **Step 3:** Implement `schema.py` and `ingest.py`:
  - Detect the delimiter with `csv.Sniffer` restricted to `,;`.
  - Normalise headers: lowercase, strip, replace spaces/`-` with `_`, then apply aliases.
  - Parse amounts with the regex `^\s*(Rp)?\s*-?\d+(\.\d+)?\s*$`. Any other text, including `\d{1,3}(\.\d{3})+`, is `BAD_AMOUNT`.
- [ ] **Step 4:** Run the tests. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(engine): file ingest with alias headers, strict amount parsing, derivation`.

---

### Task 3: Validation, master inference, preprocessing, calendar features

**Files:**
- Create: `backend/engine/validate.py`, `backend/engine/preprocess.py`, `backend/engine/calendar.py`
- Test: `backend/tests/engine/test_validate.py`, `test_preprocess.py`, `test_calendar.py`
- Modify: `backend/tests/conftest.py` (fixtures `log_df`, `master_list`, `holidays_df` loaded from `seed_dir` via `read_table`)

**Interfaces:**
- Consumes: `read_table`, `AtmMaster`, `Issue`.
- Produces:
  - `validate_log(log: pd.DataFrame, master: list[AtmMaster]) -> list[Issue]`. Codes from TR-13: `BALANCE_IDENTITY`, `CONTINUITY`, `MISSING_DATES` (one issue per gap range), `UNKNOWN_TID`.
  - `infer_master(log: pd.DataFrame, tid: str, fleet: list[AtmMaster]) -> AtmMaster`. Rules from PRD §4.1: capacity = max balance rounded **up** to 50_000_000; min = median withdrawal (1 day); cycle = median gap between replenishment dates (default 7); fill = median closing on replenishment days; denomination 100_000; cost = median fleet cost (default 1_500_000); `inferred=True`.
  - `MIN_TRAIN_DAYS = 280`
  - `allowed_as_of_range(log) -> tuple[date, date]`, per TR-20
  - `demand_series(log, tid, as_of) -> pd.Series`. Daily `DatetimeIndex` from the TID's first date to `as_of`, float, with NaN where: closing == 0 **and** withdrawal > 0 (cash-out), withdrawal == 0 with opening + replenishment > 0 (out of service), or the date is missing.
  - `fitri_days(holidays) -> list[date]`: day 1 = an `idul_fitri` date whose previous day is not `idul_fitri`.
  - `features(index: pd.DatetimeIndex, holidays: pd.DataFrame, series_start: date) -> pd.DataFrame`, with columns exactly as TR-21, in that order: `dow_1..dow_6, payday, fitri_ramadan, fitri_thr, fitri_ramp_far, fitri_ramp_near, fitri_holiday, fitri_return, year_end, new_year_day, pre_holiday, holiday, trend`.
  - `class HolidaysNotCovered(ValueError)` with code `HOLIDAYS_NOT_COVERED`.

- [ ] **Step 1: Write failing tests**:
  - `test_dummy_log_has_no_identity_errors(log_df, master_list)`: no `BALANCE_IDENTITY` issues.
  - `test_identity_and_continuity_warnings`: change one closing value → both a `BALANCE_IDENTITY` and a `CONTINUITY` warning for that tid/date.
  - `test_missing_dates_reported_as_range`: drop 2026-01-05..07 → one `MISSING_DATES` issue whose message contains `2026-01-05` and `2026-01-07`.
  - `test_infer_master_for_new_tid`: rename TID-JKT-0001's rows to `TID-NEW-1` → capacity is a multiple of 50 M and ≥ the max balance, cycle == 4, `inferred` is True.
  - `test_demand_series_censoring(log_df)`: for TID-TNG-0006, every date with `closing_balance == 0` is NaN; the count of NaN ≥ the count of cash-out days ≤ as_of.
  - `test_allowed_range_dummy(log_df)`: `== (date(2025,12,10), date(2026,10,27))`.
  - `test_fitri_days(holidays_df)`: `== [date(2025,3,31), date(2026,3,20)]`.
  - `test_feature_buckets(holidays_df)`: `fitri_ramp_near` is 1 on 2026-03-15..19, 0 on 03-14; `fitri_holiday` is 1 on 2026-03-20..26; `payday` is 1 on the 25th and 3rd and 0 on the 4th; `year_end` is 1 on 2025-12-20; `pre_holiday` is 1 on 2026-05-13 (Ascension on 05-14); and the column list equals the TR-21 order.
  - `test_features_raise_when_holidays_short`: holidays trimmed to ≤ 2026-10-31, features requested to 2026-11-26 → `HolidaysNotCovered` (coverage rule: the max holiday date must be ≥ the last requested date, or there must be a `new_year` entry after it).
- [ ] **Step 2:** Run them. Expected: FAIL.
- [ ] **Step 3:** Implement the three modules.
- [ ] **Step 4:** Run them. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(engine): validation, master inference, censored demand series, calendar features`.

---

### Task 4: Candidate models

**Files:**
- Create: `backend/engine/models/__init__.py`, `base.py`, `seasonal_naive.py`, `ets.py`, `sarimax.py`
- Test: `backend/tests/engine/test_models.py`

**Interfaces:**
- Produces:
  - `QUANTILES = (0.10, 0.50, 0.80, 0.90, 0.95)`
  - `QCOLS = ["q10","q50","q80","q90","q95"]`
  - `class Model(Protocol)`: `name: str`, `fit(y, X) -> Model`, `predict(h: int, X_future: pd.DataFrame | None) -> pd.DataFrame`. The returned frame is indexed by future dates, has columns `QCOLS`, and is ≥ 0 and monotonic across columns.
  - `SeasonalNaive()`, `Ets()`, and `Sarimax(order: tuple[int,int,int] | None = None, seasonal_order: tuple[int,int,int,int] | None = None)`
  - `select_sarimax_order(y, X) -> tuple[tuple, tuple, float]`, which returns (order, seasonal_order, aic)
  - `finalize_quantiles(df) -> df`, which clips at 0 and applies a cumulative max across columns
- Spec values (TR-22):
  - Every model fits on `log1p`.
  - Quantile `q` uses `alpha = 2*(1-q)`.
  - SARIMAX: grid p,q ∈ {0,1,2}, P,Q ∈ {0,1}, D=0, s=7. `d` comes from `adfuller` on the log series with NaN dropped (p < 0.05 → 0, else 1). `trend='c' if d==0 else 'n'`, `method='lbfgs'`, `maxiter=200`, `disp=False`. Convergence warnings are captured into `self.warnings: list[str]`.
  - ETS: `ETSModel(error="add", trend="add", damped_trend=True, seasonal="add", seasonal_periods=7)`. NaN is filled with the seasonal-naive value for fitting.
  - Seasonal naive: residual quantiles come from the 7-day-lag log residuals over the last 180 days.

- [ ] **Step 1: Write failing tests**, on a synthetic series: 400 days, weekly pattern, lognormal noise, seed 0, 5% NaN.
  - `test_predict_shape_and_monotonic[model]`, parametrised over the 3 models: `predict(30, X)` has 30 rows, columns `QCOLS`, every row non-decreasing, all ≥ 0.
  - `test_seasonal_naive_repeats_week`: q50 for day k equals y at k−7·⌈k/7⌉ (noise-free series).
  - `test_sarimax_uses_exog`: add +80% on rows where a dummy column is 1 → the predicted q50 on a future day where the flag is 1 is ≥ 1.5× the q50 on a flag-0 day.
  - `test_sarimax_order_grid_bounds`: the returned order satisfies p,q ≤ 2, P,Q ≤ 1, D == 0, s == 7.
  - `test_models_tolerate_nan`: no exception when y has NaN.
- [ ] **Step 2:** Run them. Expected: FAIL.
- [ ] **Step 3:** Implement. Wrap each statsmodels fit in `warnings.catch_warnings(record=True)`.
- [ ] **Step 4:** Run them. Expected: PASS. Note the runtime of the SARIMAX grid; if a single grid on 400 days takes > 6 s, lower `maxiter` to 100 and note it in the commit message.
- [ ] **Step 5:** Commit: `feat(engine): seasonal-naive, ETS and SARIMAX candidates with quantile output`.

---

### Task 5: Backtest and metrics

**Files:**
- Create: `backend/engine/backtest.py`
- Test: `backend/tests/engine/test_backtest.py`

**Interfaces:**
- Consumes: the models from Task 4, `features`, `MIN_TRAIN_DAYS`.
- Produces:
  - `origins(series_start: date, as_of: date) -> list[date]`. Implements `as_of − 30 − 14·i` for i = 0..7. It drops origins with fewer than `MIN_TRAIN_DAYS` of training days and raises `ValueError` if fewer than 4 remain.
  - `run_backtest(y: pd.Series, holidays, as_of: date, sarimax_orders) -> dict[str, list[dict]]`. Keys are model names; each value is a list of rows `{origin, date, y, q10, q50, q90}` (y = NaN for censored days). A model failing at an origin contributes no rows for it and records `{"origin", "error"}` under the key `"_failures"`.
  - `metrics(rows: list[dict], h: int) -> dict`. Returns `{"wape","mape","mae","coverage","n"}`, using only rows with `0 < (date − origin).days ≤ h` and non-NaN y. Formulas from TR-24.
  - `lebaran_check(y, holidays, as_of, model_name, sarimax_orders) -> dict | None`. Implements the TR-23 rule.

- [ ] **Step 1: Write failing tests**:
  - `test_origins_dummy`: `origins(date(2024,10,28), date(2026,3,6))` has 8 elements; the first is `2026-02-04` and the spacing is 14 days.
  - `test_origins_too_short_raises`: as_of `2025-11-01` → `ValueError`.
  - `test_metrics_formulas`: hand rows y = [100, 200, NaN], q50 = [110, 180, 5], h covers all → wape == 30/300, mape == mean(0.1, 0.1), mae == 15, n == 2.
  - `test_metrics_slice_by_h`: rows at day offsets 1..30 → `metrics(rows, 7)["n"] == 7`.
  - `test_backtest_no_leakage` (synthetic series): monkeypatch the model's `fit` to record `y.index.max()` → always ≤ origin.
- [ ] **Step 2:** Run them. Expected: FAIL.
- [ ] **Step 3:** Implement. Reuse the given SARIMAX orders at every origin, with no grid search per origin.
- [ ] **Step 4:** Run them. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(engine): rolling-origin backtest, pooled metrics, Lebaran check`.

---

### Task 6: Per-TID forecast pipeline

**Files:**
- Create: `backend/engine/forecast.py`
- Test: `backend/tests/engine/test_forecast.py`, `backend/tests/engine/test_golden_accuracy.py` (`@pytest.mark.slow`)

**Interfaces:**
- Consumes: Tasks 3–5.
- Produces:
  - `@dataclass class ForecastResult` with these fields:
    - `tid, as_of, engine_version, model: str, orders: dict | None`
    - `forecast: pd.DataFrame` (30 rows, index date, `QCOLS`, int)
    - `explanations: dict[date, list[str]]`
    - `backtest: dict`
    - `lebaran_check: dict | None`
    - `diagnostics: dict`
    - `fitted_q50: pd.Series` (in-sample, int)
    - methods `to_payload() -> dict` and `from_payload(d) -> ForecastResult`. The payload matches TR-27 and is JSON-serialisable, with dates as ISO strings.
  - `run_tid(tid, log, holidays, as_of) -> ForecastResult | None`. Returns `None` if the TID has fewer than `MIN_TRAIN_DAYS` of history before `as_of`. Raises `HolidaysNotCovered` if the holidays don't reach `as_of + 30`.
  - `SELECTION_H = 14` and `TIE_EPS = 0.001`. Tie preference order: `["seasonal_naive", "ets", "sarimax"]`. A model failing at more than half of the origins is ineligible (TR-25).
  - `EXPLAIN_LABELS: dict[str,str]`, e.g. `fitri_ramp_near → "pre-Lebaran"`, `fitri_ramp_far → "pre-Lebaran"`, `fitri_thr → "THR"`, `fitri_ramadan → "Ramadan"`, `fitri_holiday → "Lebaran holiday"`, `fitri_return → "post-Lebaran return"`, `year_end → "year-end"`, `payday → "payday"`, `pre_holiday → "pre-holiday"`, `holiday → "holiday"`. Explanation strings use the form `"pre-Lebaran +85%"`; take the top 2 by |uplift| (TR-26).
  - If the final fit of the winner raises, fall back to `SeasonalNaive` with `diagnostics["fallback"] = True` (TR-41).

- [ ] **Step 1: Write failing tests** (fast; use as_of `2026-03-06` on a single TID):
  - `test_run_tid_shapes(log_df, holidays_df)`: for TID-JKT-0008, the forecast has 30 rows starting 2026-03-07 and ints; `model` is in the 3 names; `from_payload(to_payload(r))` round-trips equal forecast values; `json.dumps(to_payload())` succeeds.
  - `test_short_history_returns_none`: a log truncated to 200 days → `None`.
  - `test_selection_tie_prefers_simpler`: monkeypatch `metrics` to return equal WAPE → `"seasonal_naive"`.
  - `test_fallback_on_final_fit_error`: monkeypatch `Sarimax.fit` to raise when called for the final fit, and force sarimax to win → `model == "seasonal_naive"` and `diagnostics["fallback"] is True`.
  - `test_explanations_pre_lebaran`: TID-JKT-0007 with a SARIMAX winner forced → the explanation for 2026-03-18 contains `"pre-Lebaran"`.
- [ ] **Step 2: Write the golden tests** (`slow`):
  - `test_golden_accuracy` (AC3): as_of 2026-03-06; run all 10 TIDs. At least 7 have the chosen-model WAPE at h=14 < the seasonal_naive WAPE at h=14.
  - `test_golden_lebaran` (AC4): as_of 2026-03-01; for TID-TNG-0006 and TID-JKT-0007, take the date in 2026-03-02..2026-03-22 with the max actual withdrawal; it must lie within that date's [q10, q90].
- [ ] **Step 3:** Run `pytest tests/engine/test_forecast.py -v`. Expected: FAIL.
- [ ] **Step 4:** Implement `run_tid`:
  1. Get `demand_series`, build the features up to `as_of + 30`, and select the SARIMAX order once.
  2. Run the backtest, pick the model, then do the final fit and predict 30 days.
  3. Compute the explanations, convert to ints, and store `fitted_q50` (the in-sample one-step predictions, back-transformed).
- [ ] **Step 5:** Run the fast tests (PASS), then `pytest -m slow -v`.
  Expected: PASS. If AC3 or AC4 fails, look at the per-TID metrics, adjust only the TR-22 parameters within the spec (e.g. `maxiter`), and record what changed.
- [ ] **Step 6:** Commit: `feat(engine): per-TID forecast pipeline with selection, explanations, fallback`.

---

### Task 7: Balance simulation and schedule

**Files:**
- Create: `backend/engine/plan.py` (simulation part), `backend/engine/schedule.py`
- Test: `backend/tests/engine/test_simulate.py`, `test_schedule.py`

**Interfaces:**
- Produces:
  - `@dataclass class SimResult: opening: np.ndarray; withdrawal: np.ndarray; closing: np.ndarray; cash_out: np.ndarray  # bool`
  - `simulate_balance(b0: int, demand: np.ndarray, loads: np.ndarray, cap: int) -> SimResult`. Day order per TR-19. The load is clamped to `[0, cap − balance]`. Cash-out = `closing == 0 and demand > withdrawal`.
  - `scheduled_visits(master: AtmMaster, log: pd.DataFrame, as_of: date, h: int) -> tuple[list[date], bool]`. Returns the visit dates in `(as_of, as_of+h]`, plus `assumed: bool` per TR-29. `next_visit_date`, if set, is used as the anchor.

- [ ] **Step 1: Write failing tests**:
  - `test_simulate_identity_property`: 200 random cases (seed 1), demand ∈ [0, 3e8], loads sparse → `closing == opening − withdrawal + load_clamped`, withdrawal ≤ opening + load, all ≥ 0.
  - `test_cash_out_flag`: b0 = 100, demand [60, 60], no loads → withdrawal [60, 40], cash_out [False, True].
  - `test_load_clamped_to_capacity`: b0 = 900, cap = 1000, load 500 → effective load 100.
  - `test_schedule_ignores_emergency_refill`: a synthetic log with replenishments every 4 days plus one off-phase emergency → the inferred dates continue the 4-day phase; `assumed is False`.
  - `test_schedule_next_visit_date_override`.
  - `test_schedule_no_replenishments_assumed`: → the first visit is `as_of + 1`; `assumed is True`.
- [ ] **Step 2:** Run them. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run them. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(engine): shared balance simulator and schedule inference`.

---

### Task 8: Current-policy projection and recommendation

**Files:**
- Modify: `backend/engine/plan.py`
- Test: `backend/tests/engine/test_plan.py`

**Interfaces:**
- Consumes: `simulate_balance`, `scheduled_visits`, `ForecastResult`, `AtmMaster`, `Override`.
- Produces:
  - `@dataclass class Visit`: `tid: str; date: date; kind: Literal["scheduled","extra","moved"]; amount: int; tier1_need: int; reason: str; flags: list[str]; manual: bool = False; allocated: int | None = None`
  - `Status = Literal["cash_out_risk","over_stocked","ok","insufficient_history"]`
  - `@dataclass class AtmPlan`: `tid; master: AtmMaster; status: Status; days_of_cash: int | None; b0: int; visits: list[Visit]; projection_p50: np.ndarray; projection_sl: np.ndarray; schedule_assumed: bool`
  - `project_current(master, fc: ForecastResult | None, b0, as_of, h, visit_dates) -> AtmPlan`. Loads to `current_fill_level` on each visit. Status per PRD §6.1, with `overstock_frac` (default 0.30) as a keyword argument. `fc is None` → status `insufficient_history`, no visits.
  - `recommend(master, fc, b0, as_of, h, sl: str, visit_dates, overrides: list[Override], merge: bool = True) -> AtmPlan`. Implements the PRD §6.2 need formula with `q = fc.forecast[sl→col]`:
    - Round up to the denomination and cap per TR-30. `need ≤ 0` → the visit is dropped, with a `skip` flag recorded on the plan as a zero-amount visit having `flags=["skip"]`.
    - Extra visits per PRD §6.2 / TR-31 (`kind="extra"`, reason `"Below safe minimum on <12 Mar>"` + the top explanation).
    - `tier1_need` is the same formula with q50.
    - Merge per PRD §6.2.
    - Overrides are applied last: an override amount replaces the amount, `skipped` removes the visit, `moved_from` moves it; all with `manual=True`.
  - `SL_COL = {"p50":"q50","p80":"q80","p90":"q90","p95":"q95"}`
  - `apply_loads(plan: AtmPlan, amounts: dict[date,int], fc, sl) -> AtmPlan`, which re-projects (used by allocation).

- [ ] **Step 1: Write failing tests**. Use a hand-built `ForecastResult` with a constant q50 = 100 M, q90 = 130 M, a master with cap 1 000 M, min 100 M, cycle 4, denom 100 000, fill 600 M, and b0 = 450 M.
  - `test_current_policy_status_risk`: p90 cumulative crosses min before the next visit → `cash_out_risk`.
  - `test_overstock_status`: q50 = 10 M → `over_stocked`.
  - `test_need_formula_rounding`: a visit at day 2, next at day 6 → amount == roundUp(4·130 M + 100 M − projected_before, 100 000), capped.
  - `test_skip_when_need_nonpositive`.
  - `test_extra_visit_inserted_on_peak`: q90 = 600 M/day and cap 1 000 M → extra visits on consecutive days; no visit date repeats; `capacity_shortfall` is flagged when a full load can't reach min.
  - `test_merge_suggested`.
  - `test_override_amount_and_skip`: overrides are applied, `manual=True`, and the projection is recomputed.
  - `test_capacity_below_balance_never_negative_load` (Review Focus 4): cap 300 M, b0 450 M, fill 800 M → every amount ≥ 0 and no exception.
  - `test_insufficient_history_plan` (Review Focus 2): `fc=None` → status `insufficient_history`, `visits == []`.
- [ ] **Step 2:** Run them. Expected: FAIL.
- [ ] **Step 3:** Implement. All projections call `simulate_balance`.
- [ ] **Step 4:** Run them. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(engine): current-policy projection, recommendation, extra visits, overrides`.

---

### Task 9: Budget allocation

**Files:**
- Create: `backend/engine/allocate.py`
- Test: `backend/tests/engine/test_allocate.py`

**Interfaces:**
- Consumes: `AtmPlan`, `Visit`, `apply_loads`, `ForecastResult`.
- Produces:
  - `@dataclass class Allocation: plans: list[AtmPlan]; need_total: int; funded_total: int; unused: int; underfunded: int`
  - `allocate(plans: list[AtmPlan], forecasts: dict[str, ForecastResult], sl: str, budget: int | None) -> Allocation`. It sets `Visit.allocated` for every visit and re-projects each plan.
    - `budget is None` → unconstrained.
    - Otherwise, PRD §6.3 with TR-32 tie-breaking: Tier 1 is a full pass in date order with re-projection after each allocation, then Tier 2 is proportional to `amount − tier1_need`.
    - Constrained amounts are rounded **down** to the denomination.
    - A visit with `allocated < tier1_need` gets the flag `"underfunded"` and the reason `"Underfunded – cash-out likely on <date>"`.
  - `reallocation_flows(current: list[AtmPlan], alloc: Allocation) -> list[dict]`. Implements TR-36: greedy, largest first, producing `{from_tid, to_tid, amount}`.

- [ ] **Step 1: Write failing tests** (3 hand-built ATMs, with different breach dates):
  - `test_unconstrained_funds_everything`: allocated == amount, `unused == 0` when budget is None.
  - `test_budget_70pct_tier1_order` (AC7): budget = 0.7·need → the ATM with the earliest breach has `allocated ≥ tier1_need`; `sum(allocated) ≤ budget`; every allocated value % denomination == 0; no load exceeds capacity.
  - `test_underfunding_carries_forward`: underfunding visit k raises the `tier1_need` of visit k+1 for the same ATM.
  - `test_deterministic`: two runs give identical output.
  - `test_zero_budget` (Review Focus 3): all allocated == 0, all visits flagged `underfunded`, no negative values.
  - `test_budget_above_need` (Review Focus 3): `unused == budget − need_total`.
  - `test_reallocation_flows`: an over-stocked ATM whose allocated amount is less than its current-policy load → a flow from it to the at-risk ATM; the sum of flows ≤ the total reduction.
- [ ] **Step 2:** Run them. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run them. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(engine): tiered date-ordered budget allocation and reallocation flows`.

---

### Task 10: Comparison and replay

**Files:**
- Create: `backend/engine/compare.py`
- Test: `backend/tests/engine/test_compare.py`, `test_golden_replay.py` (`slow`), `test_true_demand_isolation.py`

**Interfaces:**
- Consumes: `simulate_balance`, `AtmPlan`, `Allocation`.
- Produces:
  - `@dataclass class PolicyStats: cash_out_days: int; idle_cash: int; idle_cost: int; visits: int; visit_cost: int; loaded: int`
  - `policy_stats(plans: list[AtmPlan], demand: dict[str, np.ndarray], h: int, idle_rate: float) -> PolicyStats`. Re-simulates with `simulate_balance`. Idle cash and idle cost per PRD §6.4: `idle_cash` = the mean over ATM-days of `max(0, closing − min)`, and `idle_cost = round(idle_cash × n_atms × idle_rate × h / 365)`.
  - `@dataclass class DemandSource: basis: Literal["true_demand","estimated"]; demand: dict[str, np.ndarray]`
  - `build_demand_source(log, true_demand: pd.DataFrame | None, forecasts, as_of, h) -> DemandSource | None`. Returns `None` if `as_of + h` > the last log date. For the estimated basis, censored days use `max(logged, fitted_q50)`.
  - `compare(current, alloc, forecast_demand: dict[str,np.ndarray], replay: DemandSource | None, idle_rate, h) -> dict`, which returns the `comparison` object from TR-36.

- [ ] **Step 1: Write failing tests**:
  - `test_policy_stats_hand_case`: 1 ATM, 3 days, known numbers → exact ints.
  - `test_replay_none_when_future`.
  - `test_estimated_basis_uses_max_on_censored_days`.
  - `test_true_demand_isolation` (TR-16): read the source text of `forecast.py`, `backtest.py`, `preprocess.py`, `calendar.py` and `models/*`, and assert that `"true_demand"` doesn't appear in any of them; also assert that `run_tid`'s signature has no `true_demand` parameter.
  - `test_golden_replay` (AC8, `slow`): as_of 2026-03-01, h = 30, sl p90, unconstrained, replay basis `true_demand` → recommended `cash_out_days` < current fleet-wide, and recommended idle cash < current for each of TID-DPK-0004, TID-BKS-0005 and TID-JKT-0008 (compute per-TID stats with `policy_stats` on single-plan lists).
- [ ] **Step 2:** Run them. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `pytest tests/engine -v` and `pytest -m slow -v`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(engine): policy comparison and replay against actual demand`.

---

### Task 11: Workspace store, settings, seeding

**Files:**
- Create: `backend/app/settings.py`, `backend/app/store.py`
- Test: `backend/tests/api/test_store.py`
- Modify: `backend/tests/conftest.py` (fixture `store(tmp_path)`, which returns a seeded `Store` on a temp DB)

**Interfaces:**
- Produces:
  - `Settings` (pydantic-settings is not needed; plain dataclass + `os.environ`, prefix `CASHFC_`) with the TR-06 keys. `business_defaults: dict` with keys `h=14, sl="p90", budget=None, overstock_frac=0.30, idle_rate=0.06, detect_jump_frac=0.20`.
  - `class Store(path: Path, seed_dir: Path)`, which creates the TR-15 DDL, turns on WAL and foreign keys, and seeds if empty. Methods:
    - `seed_from_dummy() -> None`, which also resets `true_demand` and `overrides`, clears the cache, sets `source_label="Dummy data"`, and bumps the version
    - `get_log(tids: list[str] | None = None, start=None, end=None) -> pd.DataFrame`
    - `upsert_log(df, source) -> None`
    - `replace_log(df) -> None` (cascades per TR-12, empties `true_demand`)
    - `delete_log(keys: list[tuple[str,date]])`
    - `get_master() -> list[AtmMaster]`, `put_master(rows: list[AtmMaster], replace: bool = False)`
    - `get_holidays() -> pd.DataFrame`, `put_holidays(df)`
    - `get_true_demand() -> pd.DataFrame | None`
    - `get_overrides() -> list[Override]`, `put_overrides(list[Override])`, `clear_overrides()`
    - `get_setting(key)`, `set_setting(key, value)` (JSON)
    - `cache_get(key) -> dict | None`, `cache_put(key, tid, as_of, payload)`, `cache_prune(keep: int = 500)`
    - `save_issues(kind: str, issues: list[Issue])`, `get_issues() -> list[Issue]`
    - `dataset_version() -> int`, `bump_version() -> int`, `source_label()` / `set_source_label()`
    - `tid_hash(tid, as_of) -> str` (sha256 of the canonical CSV of that TID's rows ≤ as_of) and `holiday_hash() -> str`
  - All writes go through `with self._tx():`, a single transaction.

- [ ] **Step 1: Write failing tests**:
  - `test_seed_counts(store)`: 7300 log rows, 10 master rows, 45 holidays, 7300 true_demand rows, version == 1.
  - `test_upsert_bumps_version_and_changes_only_tid_hash`: editing TID-JKT-0001 on 2026-02-01 changes `tid_hash("TID-JKT-0001", 2026-03-06)` but not `tid_hash("TID-JKT-0001", 2026-01-31)` and not TID-JKT-0002's hash.
  - `test_replace_log_cascades_and_clears_true_demand`.
  - `test_cache_roundtrip_and_prune`.
  - `test_reset_restores_dummy`.
- [ ] **Step 2:** Run them. Expected: FAIL.
- [ ] **Step 3:** Implement with stdlib `sqlite3` (`check_same_thread=False`, plus one `threading.Lock` around writes).
- [ ] **Step 4:** Run them. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(app): SQLite workspace store with seeding, hashing, cache`.

---

### Task 12: Job runner and services

**Files:**
- Create: `backend/app/jobs.py`, `backend/app/services.py`
- Test: `backend/tests/api/test_services.py`

**Interfaces:**
- Consumes: `Store`, `run_tid`, the plan/allocate/compare functions.
- Produces:
  - `cache_key(tid, as_of, tid_hash, holiday_hash) -> str`, a sha256 that includes `ENGINE_VERSION`.
  - `class JobRunner(workers: int)`. Uses a `ProcessPoolExecutor`; its initializer sets the thread env vars from TR-40. Methods:
    - `submit(keys: dict[str, tuple[str, date]], payload_fn) -> str` (job_id). Keys already running are joined, not resubmitted.
    - `status(job_id) -> dict`, in the TR-38 shape.
    - Per-TID timeout is 120 s; a timeout is recorded as a failure, with the fallback per TR-41.
    - Jobs are kept for 10 minutes.
  - `_worker_run_tid(tid, log_records, holiday_records, as_of_iso) -> dict`, a top-level picklable function. It returns `{"ok": payload}` or `{"error": str, "code": str}`.
  - `class Services(store, runner, settings)`:
    - `ensure_forecasts(as_of) -> tuple[dict[str, ForecastResult | None], list[str], str | None]`: ready results, pending TIDs, job_id. Results for `None` (short history) are cached as `{"insufficient": true}`.
    - `fleet(as_of, h, sl) -> dict`, `atm(tid, as_of, h, sl, from_date) -> dict`, `plan(as_of, h, sl, budget) -> dict`, `accuracy(as_of, h) -> dict`, which build the TR-36 shapes.
    - `validate_as_of(as_of)`, which raises `ApiError(409, "AS_OF_OUT_OF_RANGE", …)`.
    - `warmup()`, which runs the scenarios from PRD §6.1: `today = (last_date, 14)`, `pre_lebaran_2026 = (2026-03-06, 21)`, `year_end_2025 = (2025-12-15, 21)`. The default scenario goes first.
  - `SCENARIOS: dict[str, tuple[date | None, int]]` (`None` = last date) and `DEFAULT_SCENARIO = "pre_lebaran_2026"`.

- [ ] **Step 1: Write failing tests** (use `JobRunner(workers=2)`; monkeypatch `_worker_run_tid` with a fast fake for the non-golden tests):
  - `test_cache_hit_no_resubmit`: two calls to `ensure_forecasts` → the second has no job.
  - `test_edit_invalidates_only_that_tid` (AC5 core): after an upsert on TID-JKT-0001, only that TID is pending.
  - `test_duplicate_submit_joined`: concurrent submits of the same key → one future.
  - `test_job_records_holiday_coverage_failure` (Review Focus 5): holidays trimmed → `status(job)["failed"]` contains `{"tid", "error"}` with `HOLIDAYS_NOT_COVERED`; `fleet()` still returns the other TIDs.
  - `test_as_of_out_of_range`: `validate_as_of(date(2025,1,1))` → `ApiError` with status 409.
- [ ] **Step 2:** Run them. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run them. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(app): process-pool job runner and service orchestration with cache keys`.

---

### Task 13: Read API (context, fleet, ATM, accuracy, status)

**Files:**
- Create: `backend/app/main.py`, `backend/app/errors.py`, `backend/app/dto.py`, `backend/app/routes/{system,fleet,atm,accuracy}.py`
- Test: `backend/tests/api/test_read_api.py`

**Interfaces:**
- Consumes: `Services`.
- Produces:
  - `create_app(settings: Settings | None = None, start_warmup: bool = True) -> FastAPI`. The lifespan creates the `Store`, `JobRunner` and `Services`, and runs the warm-up in a background thread when the flag is set.
  - `class ApiError(Exception): status: int; code: str; message: str; details: dict`, with a handler that returns the TR-35 shape. Pydantic validation errors map to 400 `BAD_PARAMS`.
  - Endpoints from ARCHITECTURE §8: `GET /api/context`, `GET /api/fleet`, `GET /api/atm/{tid}`, `GET /api/accuracy`, `GET /api/status`. The `/api/context` response is: `{data_source, min_date, max_date, as_of_min, as_of_max, tids, scenarios: [{id, label, as_of, h}], default_scenario, defaults: business_defaults, dataset_version}`.
  - `GET /api/atm/{tid}` response keys: `tid, master, status, days_of_cash, history: [{date, withdrawal, closing_balance, replenishment}], forecast: [{date, q10,q50,q80,q90,q95}], actual_after: [{date, withdrawal}] | null, projection: {current: [...], recommended: [...]}, visits: [...], explanations, model, metrics, holidays_in_view`.
  - Pydantic response models are defined for all of these (the source for `gen:api`).
  - `GET /api/settings` / `PUT /api/settings` with body `{overstock_frac?, idle_rate?, detect_jump_frac?}`. Values are validated against the TR-06 ranges, giving 400 `BAD_PARAMS` when out of range. A change to `overstock_frac` or `idle_rate` affects only the light layer and never refits.

- [ ] **Step 1: Write failing tests** (TestClient; `create_app(start_warmup=False)`; temp workspace via env vars; fake worker):
  - `test_context_defaults`: `as_of_min == "2025-12-10"`, `default_scenario == "pre_lebaran_2026"`, 3 scenarios, 10 tids.
  - `test_fleet_shape`: the keys from TR-36; while pending, `pending_tids` is non-empty and `atms` lists ready TIDs only; after the job completes, 10 ATMs.
  - `test_atm_unknown_404`: error code `UNKNOWN_TID`.
  - `test_as_of_out_of_range_409`.
  - `test_bad_h_400`: h = 45 → 400 `BAD_PARAMS`.
  - `test_fleet_with_short_history_tid` (Review Focus 2): insert TID-NEW-1 with 100 days → it appears with status `insufficient_history`; the other 9 are normal.
  - `test_settings_range_and_no_refit`: `PUT {"overstock_frac": 0.95}` → 400. `PUT {"overstock_frac": 0.5}` → 200, and the next `/api/fleet` has `pending_tids == []`.
  - `test_responses_deterministic` (TR-44): two GETs of `/api/fleet` with the same params → identical bodies after removing `job_id`.
- [ ] **Step 2:** Run them. Expected: FAIL.
- [ ] **Step 3:** Implement. Sort all lists by `tid`, then by date.
- [ ] **Step 4:** Run them. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(api): context, fleet, ATM detail, accuracy, status endpoints`.

---

### Task 14: Planner API

**Files:**
- Create: `backend/app/routes/planner.py`
- Test: `backend/tests/api/test_planner_api.py`

**Interfaces:**
- Produces:
  - `POST /api/plan` with body `{as_of, h, sl, budget: int | null}` → the TR-36 plan shape. The budget and the other inputs are also saved to `settings`.
  - `PUT /api/plan/overrides` with body `{overrides: [{tid, visit_date, amount?, skipped?, moved_from?}]}` → `{ok: true}`.
  - `DELETE /api/plan/overrides` → clears all overrides.
  - `GET /api/plan/export.csv?as_of&h&sl` → `text/csv` with header `tid,visit_date,amount,source`, where `source` is `recommended|extra|manual`.

- [ ] **Step 1: Write failing tests**:
  - `test_plan_unconstrained_funded_100pct`.
  - `test_plan_70pct_budget` (AC7 via API): `funded_total ≤ budget`, `reallocation` is non-empty for the dummy data at as_of 2026-03-06 / h 21 / sl p90 (use the real worker; mark `slow`).
  - `test_override_applied_then_cleared`.
  - `test_export_csv_header_and_rows`.
  - `test_plan_latency` (`perf`): warm cache → `POST /api/plan` server time ≤ 300 ms (TR-39).
- [ ] **Step 2:** Run them. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run them. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(api): plan, overrides, CSV export`.

---

### Task 15: Data API (grid CRUD, upload, validation, reset)

**Files:**
- Create: `backend/app/routes/data.py`
- Test: `backend/tests/api/test_data_api.py`, `backend/tests/api/test_upload.py`, `backend/tests/perf/test_perf.py`

**Interfaces:**
- Produces the endpoints from ARCHITECTURE §8 and TR-37:
  - `GET /api/data/log?tid&from&to&page&page_size(=200)` → `{rows, total}`
  - `PATCH /api/data/log` (batch partial update, `source="edit"`), `POST /api/data/log` (add rows), `DELETE /api/data/log` (`{keys:[{tid,date}]}`)
  - `GET/PUT /api/data/master`, `GET/PUT /api/data/holidays`
  - `POST /api/data/upload` (multipart: `file`, `kind`, `mode`)
  - `GET /api/data/validation`, `GET /api/data/download?kind=log|master|holidays`, `POST /api/data/reset`
  - Every write: run `validate_log`, infer master rows for unknown TIDs, save the issues, bump the version, call `ensure_forecasts(current as_of)` → return the TR-37 body.
  - Size limit: 413 `FILE_TOO_LARGE` above `MAX_UPLOAD_MB`. `UnreadableFile` → 422 with its issues.

- [ ] **Step 1: Write failing tests**:
  - `test_patch_row_recompute_only_that_tid` (AC5): PATCH the TID-JKT-0001 withdrawal on 2026-03-06 ×3 → `job.pending_tids == ["TID-JKT-0001"]`. A `slow` variant with the real worker: done in ≤ 5 s and the fleet `recommended_amount` for that TID changed.
  - `test_patch_breaking_identity_saved_with_warning`.
  - `test_upload_replace_valid_csv` (AC6): upload the dummy log → `source_label` is the file name and `true_demand` is empty.
  - `test_upload_broken_rows`: a file with 2 bad dates and 1 negative → 200, issues include `BAD_DATE`×2 and `NEGATIVE_VALUE`, and the remaining rows are stored.
  - `test_upload_missing_column_422`.
  - `test_upload_unknown_tid_infers_master` (AC10): the master row has `inferred: true`, and the forecast job includes that TID.
  - `test_upload_semicolon_rp_prefix` (Review Focus 1): `;`-delimited, `Rp` prefixes, one `1.000.000` → 200, one `BAD_AMOUNT`, the rest stored.
  - `test_upload_xlsx_alias_headers`.
  - `test_upload_too_large_413` (set `MAX_UPLOAD_MB=0.001` via settings).
  - `test_reset_restores_dummy`.
  - `tests/perf/test_perf.py` (`perf`): a cold forecast of all 10 TIDs ≤ 60 s; uploading the full dummy CSV ≤ 3 s; `GET /api/fleet` and `GET /api/atm/{tid}` warm ≤ 300 ms (TR-39).
- [ ] **Step 2:** Run them. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `pytest -m "not perf" -v`, then `pytest -m perf -v` once. Expected: PASS. If perf fails, record the timings in the commit message and apply the ARCHITECTURE §5 mitigations before moving on.
- [ ] **Step 5:** Commit: `feat(api): data grid CRUD, uploads with validation, reset; perf tests`.

---

### Task 16: Frontend scaffold, header controls, static serving, run scripts

**Files:**
- Create: `frontend/` (Vite React TS template), `frontend/src/{main.tsx,App.tsx,routes.tsx}`, `src/api/{client.ts,schema.d.ts,hooks.ts}`, `src/state/controls.ts`, `src/lib/format.ts`, `src/components/{Header.tsx,StatusBadge.tsx,KpiTile.tsx,Spinner.tsx}`, `scripts/run.ps1`, `scripts/dev.ps1`
- Modify: `backend/app/main.py` (mount `frontend/dist` at `/` with an SPA fallback to `index.html` for non-`/api` paths)
- Test: `frontend/src/lib/format.test.ts`, `frontend/src/state/controls.test.ts`

**Interfaces:**
- Produces:
  - `formatRp(n: number): string` → `"Rp 640.000.000"`
  - `formatRpCompact(n)` → `"Rp 640 jt"`, `"Rp 1,2 M"` (≥ 1e9 → M with 1 decimal, ≥ 1e6 → jt with no decimals)
  - `formatDate(iso: string): string` → `"12 Mar 2026"`
  - `useControls()` (Zustand), with `{scenario, asOf, h, sl, setScenario, setAsOf, setH, setSl}`, kept in sync with the URL query (`?as_of=&h=&sl=`)
  - API hooks: `useContext()`, `useFleet()`, `useAtm(tid)`, `usePlan(budget)`, `useAccuracy()`, `useJobStatus(jobId)` (refetchInterval 500 ms while `!done`), and mutations that invalidate on `dataset_version`
  - npm scripts: `dev`, `build`, `lint`, `test` (`vitest run`), `gen:api` (`openapi-typescript http://127.0.0.1:8000/openapi.json -o src/api/schema.d.ts`), `e2e`
  - `StatusBadge` colours: cash_out_risk red, over_stocked amber, ok green, insufficient_history grey. Each badge always shows its text label.

- [ ] **Step 1:** Scaffold with `npm create vite@5 frontend -- --template react-ts`. Install the TR-03 packages. Set up Tailwind (system font stack, no Google Fonts) and a Vite proxy from `/api` to `http://127.0.0.1:8000`.
- [ ] **Step 2: Write failing tests**:
  - `formatRp(640000000) === "Rp 640.000.000"`
  - `formatRpCompact(640000000) === "Rp 640 jt"`
  - `formatRpCompact(1234500000) === "Rp 1,2 M"`
  - `formatDate("2026-03-12") === "12 Mar 2026"`
  - Controls: `setScenario("pre_lebaran_2026")` with the context → `asOf === "2026-03-06"` and `h === 21`.
- [ ] **Step 3:** Run `npx vitest run`. Expected: FAIL.
- [ ] **Step 4:** Implement the formatters, the store, and the Header (scenario select, as-of picker bounded to `as_of_min..as_of_max`, h slider 7–30, sl select, data source badge, "Forecasting 3/10" progress), plus the routes `/`, `/atm/:tid`, `/planner`, `/data`, `/accuracy` with placeholder pages. Run `npm run gen:api` against the running backend.
- [ ] **Step 5:** Write `scripts/run.ps1`:
  1. Create `backend/.venv` if missing and `pip install -e backend` on first run.
  2. Run `npm ci` and `npm run build` if `frontend/dist` is older than `frontend/src`.
  3. Start `uvicorn app.main:app --host 127.0.0.1 --port 8000` from `backend`.
  4. Open `http://127.0.0.1:8000`.

  Also write `scripts/dev.ps1`, which starts `uvicorn --reload` and `npm run dev` in two windows.
- [ ] **Step 6:** Verify: `npx vitest run` PASS, `npm run lint` clean, `npm run build` OK. Run `scripts\run.ps1` and check that the browser shows the header with the Pre-Lebaran scenario selected and that the API is reachable.
- [ ] **Step 7:** Commit: `feat(web): scaffold, header controls, formatting, static serving, run scripts`.

---

### Task 17: Fleet Overview and ATM Detail pages

**Files:**
- Create: `frontend/src/pages/{FleetOverview.tsx,AtmDetail.tsx}`, `src/components/{BalanceGauge.tsx,RecommendationCard.tsx}`, `src/components/charts/{DemandForecastChart.tsx,BalanceChart.tsx,chartTheme.ts}`
- Test: `frontend/src/components/charts/chartOptions.test.ts`

**Interfaces:**
- Consumes: `useFleet`, `useAtm`, the formatters.
- Produces:
  - `buildDemandOption(atm: AtmResponse): EChartsOption`, a pure function containing:
    - series `actual`, `q50`, and the band as two stacked areas `band_low` (q10) and `band_span` (q90 − q10);
    - holiday `markArea` entries, labelled `"Lebaran"` for the `idul_fitri`/`cuti_bersama` window;
    - a dashed `actual_after` series when present.
  - `buildBalanceOption(atm): EChartsOption`, with series `actual_balance` (markPoints on replenishment days), `current_projection`, `recommended_projection`, a markLine at `min_safe_balance`, and visit markers.
  - Both charts use `dataZoom` with a default window of the last 90 days of history plus the forecast.

- [ ] **Step 1: Write failing tests** on a fixture `AtmResponse` JSON:
  - The band series exist and are stacked.
  - A markArea labelled `"Lebaran"` exists when the view covers 2026-03-20.
  - `actual_after` has `lineStyle.type === "dashed"`.
  - The min markLine value equals `master.min_safe_balance`.
- [ ] **Step 2:** Run them. Expected: FAIL.
- [ ] **Step 3:** Implement the option builders and the pages:
  - **Fleet**: KPI tiles, and a sortable table/cards with one row per TID (status badge, gauge, days of cash, next visit, recommended amount, link to detail, and an "inferred master – review" chip when the master was inferred).
  - **Detail**: the two charts, the recommendation card (reason text from the API, model name and WAPE), and a fallback notice when `diagnostics.fallback`.
- [ ] **Step 4:** Run `npx vitest run`, `npm run lint` and `npm run build`. Expected: PASS. Run the app and check visually on Pre-Lebaran: the terminal shows a band rising before 20 Mar, and the hospital shows over-stocked.
- [ ] **Step 5:** Commit: `feat(web): fleet overview and ATM detail with forecast and balance charts`.

---

### Task 18: Allocation Planner page

**Files:**
- Create: `frontend/src/pages/Planner.tsx`, `src/components/{PlanGrid.tsx,ComparisonPanel.tsx}`, `src/components/charts/ReallocationSankey.tsx`
- Test: `frontend/src/components/charts/sankey.test.ts`, `src/components/planGrid.test.ts`

**Interfaces:**
- Consumes: `usePlan`, override mutations, export URL.
- Produces:
  - `buildSankeyOption(flows: {from_tid,to_tid,amount}[], names: Record<string,string>): EChartsOption`. Node names are prefixed `"↑ "` for donors and `"↓ "` for receivers, so a TID can't create a cycle.
  - `rowsFromPlan(plan): PlanRow[]` and `overridesFromEdits(rows, edits): Override[]`, as pure helpers.
  - Budget input: an IDR text box (digits only, shown formatted), an "Unconstrained" toggle, and a "70% of need" quick button. Edits are debounced by 300 ms.

- [ ] **Step 1: Write failing tests**:
  - Sankey links preserve amounts, and donor and receiver nodes are distinct.
  - Editing an amount cell → one override with that tid/date/amount.
  - Toggling skip → `skipped: true`.
- [ ] **Step 2:** Run them. Expected: FAIL.
- [ ] **Step 3:** Implement the page:
  - The header shows need, funded % and underfunded count.
  - AG Grid with editable `visit_date`/`amount`/`skip` columns, a `kind` column (scheduled/extra/moved), reason, and flags shown as chips (underfunded in red).
  - Sankey, the comparison panel (current vs recommended, plus a replay block labelled "Actual (true demand)" or "Estimated"), and the Export CSV and Clear overrides buttons.
  - A "Settings" popover for the over-stock threshold (10–90%) and the idle-cash rate (0–30%), saved through `PUT /api/settings`.
- [ ] **Step 4:** Run `npx vitest run`, lint and build. Expected: PASS. Check manually: with a budget at 70%, the Sankey shows hospital/campus/residential → terminal/airport/mall.
- [ ] **Step 5:** Commit: `feat(web): allocation planner with overrides, reallocation sankey, comparison`.

---

### Task 19: Data Editor and Accuracy pages

**Files:**
- Create: `frontend/src/pages/{DataEditor.tsx,Accuracy.tsx}`, `src/components/{UploadDialog.tsx,ValidationPanel.tsx}`, `src/components/charts/BacktestChart.tsx`
- Test: `frontend/src/components/validationPanel.test.tsx`

**Interfaces:**
- Consumes: the data endpoints (Task 15), `useAccuracy`.
- Produces:
  - The DataEditor has three tabs: Daily Log, ATM Master, Holidays.
    - The log grid uses server-side pagination (page_size 200) with TID and date-range filters, inline edit with batch save, add row, and delete selected.
    - Upload dialog: file, kind, and mode (Replace/Merge).
    - Reset to dummy data (with a confirm dialog) and Download buttons.
  - `ValidationPanel` groups issues by severity (error, then warning, then info), with counts and the first 50 rows of each group, plus a filter by TID.
  - The Accuracy page has a table per TID: chosen model, WAPE, MAPE, MAE, coverage, Lebaran-check error, the baseline WAPE, and a "beats baseline" ✓. It also shows a BacktestChart for the selected TID and origin.

- [ ] **Step 1: Write a failing test**: ValidationPanel with 3 issues (one per severity) → three headers in order error, warning, info, and the TID filter narrows the rows.
- [ ] **Step 2:** Run it. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `npx vitest run`, lint and build. Expected: PASS. Check manually: edit one withdrawal → the header shows "Forecasting 1/10", then the Fleet amount changes; upload a broken CSV → issues shown and no crash.
- [ ] **Step 5:** Commit: `feat(web): data editor with upload/validation/reset and accuracy page`.

---

### Task 20: End-to-end smoke and final verification

**Files:**
- Create: `frontend/playwright.config.ts`, `frontend/tests/e2e/demo.spec.ts`

**Interfaces:**
- Consumes: the whole app, started by Playwright `webServer` with `scripts/run.ps1` (or `uvicorn` against the built dist) on a fresh temporary workspace (`CASHFC_WORKSPACE_DB` set to a temp file).

- [ ] **Step 1: Write the tests**:
  - `all routes render without console errors` (AC2): visit the 5 routes and fail on any `console.error` or `pageerror`.
  - `pre-lebaran shows risk and overstock` (AC9): on `/`, wait until progress is done → at least one "Cash-out risk" badge and at least one "Over-stocked" badge.
  - `planner reallocation at 70%` (AC9): click "70% of need" → at least one Sankey link (assert through `data-testid="sankey-links-count"` > 0).
  - `edit recompute` (AC5): edit one row in the Data Editor → the Fleet `recommended_amount` for that TID changes within 10 s (UI budget includes polling).
- [ ] **Step 2:** Run `npx playwright install chromium`, then `npm run e2e`. Expected: PASS.
- [ ] **Step 3: Full verification** (TR-46):
  - `cd backend; ruff check .; ruff format --check .; pytest -m "not perf"; pytest -m slow; pytest -m perf`
  - `cd frontend; npm run lint; npx vitest run; npm run build; npm run e2e`

  Expected: everything passes. Report any perf numbers that are over a limit, with the measured values.
- [ ] **Step 4:** Offline check: disconnect the network, run `scripts\run.ps1`, and walk through the PRD §3 demo story. Expected: it works with no network requests outside 127.0.0.1 (check the DevTools Network tab).
- [ ] **Step 5:** Update the Commands section of `CLAUDE.md`: drop the "planned" wording and keep the commands that actually work.
- [ ] **Step 6:** Commit: `test(e2e): demo smoke tests; docs: finalize commands`.
