# TRD — ATM Cash Forecasting & Replenishment Demo

| | |
|---|---|
| **Status** | Draft v1 — for review |
| **Date** | 2026-10-28 |
| **Inputs** | [`PRD.md`](PRD.md) (what & business rules), [`ARCHITECTURE.md`](ARCHITECTURE.md) (structure & flows) |

This document gives the **exact technical requirements** the code must meet: environment, configuration, file and database formats, engine interfaces, algorithm parameters, API contracts, performance, error handling, and tests. Each requirement has an ID (`TR-xx`) so tests and reviews can refer to it. Where this document fixes a number or rule that the PRD left open, it is marked **[Claude's call]**.

Conventions: "must" is required, and "should" is expected unless there is a stated reason not to. Dates are `YYYY-MM-DD` in Asia/Jakarta time; there are no timezones or intraday times. Money is integer IDR.

---

## 1. Environment & dependencies

**TR-01**: The backend runs in a project-local virtual environment `backend/.venv` with Python 3.13 (installed). Global site-packages must not be used.

```powershell
cd D:\Training\backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
```

**TR-02**: Backend dependencies are declared in `backend/pyproject.toml`. The minimum versions below are known to support Python 3.13. At scaffold time, generate a lock file (`pip freeze > requirements.lock`) and commit it, so the demo laptop installs exactly the tested set.

| Package | Min version | Use |
|---|---|---|
| numpy | 2.1 | arrays |
| pandas | 2.2.3 | data frames |
| scipy | 1.14.1 | stats helpers (ADF via statsmodels, norm quantiles) |
| statsmodels | 0.14.4 | SARIMAX, ETS, ADF test |
| fastapi | 0.115 | API |
| uvicorn[standard] | 0.32 | ASGI server |
| pydantic | 2.9 | DTOs |
| python-multipart | 0.0.18 | uploads |
| openpyxl | 3.1.5 | XLSX read |
| *dev:* pytest, httpx, ruff | 8.3 / 0.27 / 0.7 | tests, API client, lint+format |

**TR-03**: Frontend uses Node 24 (installed) with npm, and `package-lock.json` is committed. Main packages: react 18.3, react-dom 18.3, react-router-dom 6.28, vite 5.4, typescript 5.6, @tanstack/react-query 5, zustand 5, echarts 5.5, echarts-for-react 3, ag-grid-community + ag-grid-react 32, tailwindcss 3.4. Dev: vitest 2, @playwright/test 1.48, openapi-typescript 7, eslint 9, prettier 3.

**TR-04**: After the first install, the app must run with **no network access**. There must be no CDN links and no web fonts fetched at runtime (use the system font stack or bundled fonts).

**TR-05**: Lint and format with `ruff check` + `ruff format` (backend), and `eslint` + `prettier` (frontend). CI is not required; the commands must pass locally before a task is called done.

## 2. Configuration

**TR-06**: `app/settings.py` reads settings from environment variables with the prefix `CASHFC_`, falling back to the defaults below. Business defaults that the user can change in the UI are stored in the SQLite `settings` table. Env vars only set their initial values.

| Key | Default | Notes |
|---|---|---|
| `HOST` / `PORT` | `127.0.0.1` / `8000` | Must bind to loopback only |
| `WORKSPACE_DB` | `workspace/workspace.db` | Created on first run |
| `SEED_DIR` | `data/` | Dummy CSVs |
| `WORKERS` | `max(1, cpu_count − 1)` | Process pool size |
| `MAX_UPLOAD_MB` | `20` | |
| `WARMUP_SCENARIOS` | `true` | Pre-compute the demo scenarios at startup |
| `ENGINE_VERSION` | constant in `engine/__init__.py` | Not an env var; bump on model changes |

UI-editable business defaults **[Claude's call]**, in line with the PRD:

| Setting | Default | Range |
|---|---|---|
| horizon `h` | 14 | 7–30 |
| service level `sl` | `p90` | `p50`, `p80`, `p90`, `p95` |
| budget | `null` (= unconstrained) | ≥ 0 IDR |
| over-stock threshold | 0.30 × capacity | 0.10–0.90 |
| idle-cash annual rate | 0.06 | 0–0.30 |
| replenishment detection jump | 0.20 × capacity | 0.05–0.80 |

## 3. Input files

**TR-07**: Formats:
- **CSV**: UTF-8 (a BOM is allowed). The delimiter is auto-detected (`,` or `;`). The first row is the header.
- **XLSX**: only the first sheet is read, and the first row is the header.
- The max size is `MAX_UPLOAD_MB`.

**TR-08**: Header names are matched case-insensitively after trimming, and spaces and `-` are treated as `_`. The aliases below are accepted, so typical Indonesian client exports load without manual renaming **[Claude's call]**:

| Canonical | Aliases |
|---|---|
| `tid` | `terminal_id`, `atm_id`, `id_atm` |
| `date` | `tanggal`, `tgl`, `log_date` |
| `opening_balance` | `saldo_awal`, `open_balance` |
| `withdrawal` | `penarikan`, `tarik_tunai`, `cash_out` |
| `replenishment` | `isi_ulang`, `pengisian`, `cash_in`, `refill` |
| `closing_balance` | `saldo_akhir`, `close_balance`, `end_balance` |

Unknown columns are ignored and reported as an `info` issue.

**TR-09**: Parsing values:
- **Dates**: `YYYY-MM-DD`, `DD/MM/YYYY`, `DD-MM-YYYY`, or native Excel dates. Any other format makes the row invalid.
- **Amounts**: integers, or decimals with `.` (rounded to the nearest rupiah). An optional `Rp` prefix and spaces are stripped.
  - Thousand separators are **not** guessed. A value like `1.000.000` is an `error` issue for that row, because `.` and `,` are ambiguous in id-ID exports.
  - XLSX numeric cells are always fine.

**TR-10**: Required columns are `tid`, `date`, `opening_balance`, `closing_balance`. `withdrawal` and `replenishment` are optional, and if missing they are derived as specified in PRD §4.1 (detection threshold from TR-06). Derived values are stored with `source = 'derived'`.

**TR-11**: Multiple rows for the same (`tid`, `date`) in a file are aggregated **[Claude's call]**:
- `opening_balance` = first row of the day (file order);
- `closing_balance` = last row;
- `withdrawal` and `replenishment` = sums.

An `info` issue is raised. This covers logs with intraday entries (PRD §10).

**TR-12**: Upload modes:
- `replace` replaces the whole table of that kind. For `log`, it also deletes master rows and overrides for TIDs that are no longer present.
- `merge` upserts by key.

Both modes run in one SQLite transaction. If the file cannot be read at all (bad encoding, missing required columns), nothing is written and an HTTP 422 is returned.

## 4. Validation

**TR-13**: `engine/validate.py` returns a list of issues. Each issue is `{severity: error|warning|info, code, tid?, date?, message}`. Codes:

| Code | Severity | Rule |
|---|---|---|
| `MISSING_COLUMN` | error (file) | A required column is absent |
| `BAD_DATE` / `BAD_AMOUNT` | error (row) | Value cannot be parsed. The row is not stored |
| `NEGATIVE_VALUE` | error (row) | Any amount < 0. The row is not stored |
| `DUPLICATE_KEY` | info | Aggregated per TR-11 |
| `BALANCE_IDENTITY` | warning | `closing ≠ opening − withdrawal + replenishment`. Stored as is |
| `CONTINUITY` | warning | `opening(d) ≠ closing(d−1)` |
| `MISSING_DATES` | warning | Gaps in a TID's date range (reported as ranges) |
| `UNKNOWN_TID` | warning | Master row auto-inferred (PRD §4.1), flagged `inferred = 1` |
| `SHORT_HISTORY` | warning | A TID has less than `MIN_TRAIN_DAYS` (TR-20) before as-of. That TID gets no model forecast and is shown as "insufficient history" |
| `UNKNOWN_COLUMN` | info | Column ignored |

**TR-14**: Validation runs on every write and the result is stored, so `GET /api/data/validation` does not re-validate.

## 5. Database (SQLite)

**TR-15**: Schema, created by `app/store.py` on startup if missing. Turn on `PRAGMA journal_mode=WAL` and `foreign_keys=ON`.

```sql
CREATE TABLE atm_master (
  tid TEXT PRIMARY KEY, location_name TEXT, location_type TEXT,
  capacity INTEGER NOT NULL, min_safe_balance INTEGER NOT NULL,
  replenish_cycle_days INTEGER NOT NULL CHECK (replenish_cycle_days BETWEEN 1 AND 31),
  denomination INTEGER NOT NULL CHECK (denomination IN (50000, 100000)),
  cost_per_visit INTEGER NOT NULL, current_fill_level INTEGER NOT NULL,
  next_visit_date TEXT, inferred INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE daily_log (
  tid TEXT NOT NULL REFERENCES atm_master(tid) ON DELETE CASCADE,
  date TEXT NOT NULL,
  opening_balance INTEGER NOT NULL, withdrawal INTEGER NOT NULL,
  replenishment INTEGER NOT NULL, closing_balance INTEGER NOT NULL,
  source TEXT NOT NULL CHECK (source IN ('dummy','upload','edit','derived')),
  PRIMARY KEY (tid, date)
);
CREATE TABLE holidays (date TEXT PRIMARY KEY, name TEXT NOT NULL,
  type TEXT NOT NULL CHECK (type IN ('new_year','christmas','idul_fitri','cuti_bersama','national')));
CREATE TABLE true_demand (tid TEXT NOT NULL, date TEXT NOT NULL, true_demand INTEGER NOT NULL,
  PRIMARY KEY (tid, date));
CREATE TABLE overrides (tid TEXT NOT NULL REFERENCES atm_master(tid) ON DELETE CASCADE,
  visit_date TEXT NOT NULL, amount INTEGER, skipped INTEGER NOT NULL DEFAULT 0,
  moved_from TEXT, PRIMARY KEY (tid, visit_date));
CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);           -- JSON values
CREATE TABLE forecast_cache (cache_key TEXT PRIMARY KEY, tid TEXT NOT NULL, as_of TEXT NOT NULL,
  created_at TEXT NOT NULL, payload TEXT NOT NULL);                            -- JSON, see TR-27
CREATE TABLE validation_issues (id INTEGER PRIMARY KEY, kind TEXT, severity TEXT, code TEXT,
  tid TEXT, date TEXT, message TEXT);
CREATE TABLE dataset_meta (id INTEGER PRIMARY KEY CHECK (id = 1), dataset_version INTEGER NOT NULL,
  source_label TEXT NOT NULL);
```

**TR-16**: The `true_demand` table is filled **only** from `data/atm_true_demand.csv` when seeding the dummy data. Any upload or `replace` of the log empties it. Only `compare.py` may receive its data, and a test checks that the forecasting modules never import or read it.

**TR-17**: `forecast_cache` is pruned at startup to the newest 500 entries. Reset to dummy data clears it, except the warm-up results recomputed right after.

## 6. Engine interfaces

**TR-18**: Public signatures are typed. DataFrames use the canonical column names. The time index is a `pandas.DatetimeIndex` with daily frequency.

```python
# preprocess.py
def demand_series(log: pd.DataFrame, tid: str, as_of: date) -> pd.Series      # float, NaN on censored days
# calendar.py
def features(index: pd.DatetimeIndex, holidays: pd.DataFrame) -> pd.DataFrame  # TR-21 columns
# models/base.py
class Model(Protocol):
    name: str
    def fit(self, y: pd.Series, X: pd.DataFrame | None) -> "Model": ...
    def predict(self, h: int, X_future: pd.DataFrame | None) -> pd.DataFrame  # cols q10,q50,q80,q90,q95
# forecast.py
def run_tid(tid: str, log: pd.DataFrame, holidays: pd.DataFrame, as_of: date) -> ForecastResult
# schedule.py
def scheduled_visits(master: AtmMaster, log: pd.DataFrame, as_of: date, h: int) -> list[date]
# plan.py
def simulate_balance(b0: int, demand: np.ndarray, loads: np.ndarray, cap: int) -> SimResult
def recommend(master: AtmMaster, fc: ForecastResult, b0: int, as_of: date, h: int,
              sl: str, overrides: list[Override]) -> AtmPlan
# allocate.py
def allocate(plans: list[AtmPlan], budget: int | None) -> Allocation
# compare.py
def compare(current: list[AtmPlan], recommended: Allocation, demand_source: DemandSource,
            idle_rate: float) -> Comparison
```

**TR-19**: `simulate_balance` is the only balance simulator, and both planning and replay use it. Daily order: **load in the morning → withdraw → close**. `withdrawal = min(demand, balance + load)`. A day counts as a **cash-out day** if `closing == 0` and `demand > withdrawal`.

## 7. Forecasting algorithm parameters

**TR-20**: History requirements **[Claude's call]**:
- `MIN_TRAIN_DAYS = 280`.
- The allowed as-of range is from `first_date + 280 + 30 + 14×7` to `last_date`. For the dummy data that is **2025-12-10** → **2026-10-27**, which allows all three PRD demo scenarios.
- The UI date picker is limited to this range.

**TR-21**: Calendar feature columns, all 0/1 except `trend`:
- `dow_1`…`dow_6` (Monday is the reference)
- `payday` (day ≥ 25 or ≤ 3)
- `fitri_ramadan` (days to Idul Fitri day 1 in 21–30), `fitri_thr` (11–20), `fitri_ramp_far` (6–10), `fitri_ramp_near` (1–5), `fitri_holiday` (0 to −6), `fitri_return` (−7 to −13)
- `year_end` (20–31 Dec), `new_year_day`
- `pre_holiday` (the next day is a `national` holiday), `holiday` (the day is `national`, `christmas` or `cuti_bersama`, outside the Fitri window)
- `trend` = days since the series start divided by 365

The Fitri ramp is split into two buckets **[Claude's call]** so the model can capture the steep last days. The features for future dates come from the holiday table, and a forecast fails with a clear error if the table does not cover `as_of + 30`.

**TR-22**: Candidate model specs:

| Model | Spec |
|---|---|
| `seasonal_naive` | `ŷ(t+k) = y(t+k−7⌈k/7⌉)`, NaN filled with the last non-NaN value of the same weekday. Quantiles are empirical quantiles of the 7-day-lag log residuals over the last 180 days, added on the log scale |
| `ets` | `statsmodels ETSModel` on `log1p(y)`: error add, trend add damped, seasonal add, period 7. Censored values are filled with the seasonal-naive value for fitting only. Quantiles come from `get_prediction().summary_frame(alpha)` at each needed level |
| `sarimax` | `SARIMAX(log1p(y), exog=X, order=(p,d,q), seasonal_order=(P,0,Q,7), trend='c' if d==0 else 'n')`. Missing values are left as NaN (Kalman filter). Grid: p,q ∈ {0,1,2}, P,Q ∈ {0,1}. d is chosen by an ADF test on the log series (p < 0.05 → d=0, else 1). The best order by AIC on the full history is reused for all backtest origins. Fit: `method='lbfgs'`, `maxiter=200`, `disp=False`. Quantiles come from `get_forecast(h, exog).conf_int(alpha)` on the log scale, back-transformed with `expm1` |

Quantile level q comes from the two-sided interval with `alpha = 2(1 − q)`. Every quantile is clipped at ≥ 0 and made monotonic across levels.

**TR-23**: Backtest:
- Origins are `o_i = as_of − 30 − 14·i` for `i = 0…7`. Origins whose training length is less than `MIN_TRAIN_DAYS` are skipped, and at least 4 origins are required.
- Each candidate is re-fit on data ≤ `o_i` and forecasts `o_i+1 … o_i+30`. Scoring uses only days whose actual value is not NaN.
- **Lebaran check**: origin = Idul Fitri day 1 − 14. It is computed only if that origin + 30 ≤ as_of and the training length is ≥ `MIN_TRAIN_DAYS`. Its score is reported separately and does not count in model selection.

**TR-24**: Metrics are computed over the scored days within the first `h` days of each origin and pooled across origins:
- `WAPE = Σ|y − ŷ₅₀| / Σ y`
- `MAPE = mean(|y − ŷ₅₀| / y)` over days with y > 0
- `MAE = mean |y − ŷ₅₀|` (IDR)
- `coverage = share of y in [q10, q90]`

Because the metrics are stored per origin per day, they can be re-sliced for any h ≤ 30 without refitting.

**TR-25**: Selection: the candidate with the lowest WAPE at **h = 14** is chosen **[Claude's call]**. The chosen model does not change when the user changes h, so the page does not jump between models. On a tie (difference < 0.001), the simpler model wins: naive, then ETS, then SARIMAX. A model that fails on more than half of the origins is not eligible.

**TR-26**: Explanations (SARIMAX winner): for each forecast day, take the exogenous columns that are active and multiply them out to an uplift: `uplift_% = (exp(Σ βⱼ xⱼ) − 1) × 100`. The top two contributors are shown, with labels from a fixed map (e.g. `fitri_ramp_near` → "pre-Lebaran"). For ETS or naive winners, the uplift is versus the mean of the same weekday over the last 4 weeks.

**TR-27**: The `forecast_cache.payload` JSON contains:
- `tid`, `as_of`, `engine_version`
- `model` (chosen), `orders` (if SARIMAX)
- `forecast`: 30 entries of `{date, q10, q50, q80, q90, q95}` (integer IDR)
- `explanations` per day
- `backtest`: per candidate, per origin, per day `{date, y, q10, q50, q90}`
- `lebaran_check`
- `diagnostics` (warnings, fit seconds)
- `fitted_in_sample_q50` (for censored-day imputation, PRD §6.4)

## 8. Planning algorithm parameters

**TR-28**: Day indexing: `as_of` is the last known day. `B0 = closing_balance(as_of)`. The horizon is `as_of+1 … as_of+h`.

**TR-29**: Schedule inference (PRD §6.1):
1. Take the replenishment dates in `(as_of − 90, as_of]`.
2. Compute the phase of each date as `ordinal(date) mod cycle` and take the most common phase. On a tie, pick the phase of the latest date.
3. If there are no replenishments in that window, use `as_of + 1` as the phase anchor and mark the schedule as `assumed`.

**TR-30**: Need and rounding:
- `need(v)` follows the PRD §6.2 formula, with `q(d)` = the forecast quantile for the selected `sl`. The daily quantiles are summed over the cycle. This is deliberately conservative **[Claude's call]**; a quantile-of-sum is listed as a future refinement.
- Unconstrained amounts are rounded **up** to the denomination. Budget-constrained amounts are rounded **down**.
- Each load is capped at `capacity − balance before load`.

**TR-31**: Extra visits are inserted while walking forward through the days, as PRD §6.2 describes. There is a guard of at most one visit per ATM per day. If a full load on day *d* still breaches `min` on day *d*, the day is flagged `capacity_shortfall` instead of looping.

**TR-32**: Allocation tie-breaking within a date: earliest projected breach date first, then larger Tier-1 deficit, then `tid` ascending. Allocation must be deterministic.

**TR-33**: Visit costs and idle cash follow PRD §6.4. Every amount in the API output is an integer.

## 9. API contracts

**TR-34**: All endpoints are under `/api` and use JSON with `snake_case` keys. Dates are ISO strings and amounts are integers. Pydantic models in `app/dto.py` are the source of truth. The frontend types are generated from `/openapi.json` with `npm run gen:api`.

**TR-35**: Errors use one shape, with HTTP 400 (bad params), 404 (unknown TID), 409 (as-of out of range), 413 (file too large), 422 (unreadable file / validation), 500 (unexpected):

```json
{ "error": { "code": "AS_OF_OUT_OF_RANGE", "message": "as_of must be between 2025-12-10 and 2026-10-27", "details": {} } }
```

**TR-36**: Key payloads (abbreviated):

```jsonc
// GET /api/fleet?as_of=2026-03-06&h=21&sl=p90
{ "as_of": "2026-03-06", "h": 21, "sl": "p90", "dataset_version": 3,
  "pending_tids": [], "job_id": null,
  "kpis": { "at_risk": 4, "over_stocked": 3, "idle_cash": 1234500000, "recommended_total": 9876000000 },
  "atms": [ { "tid": "TID-JKT-0007", "location_name": "Terminal Pulo Gebang", "location_type": "bus_terminal",
              "balance": 212300000, "capacity": 900000000, "days_of_cash": 1, "status": "cash_out_risk",
              "next_visit": "2026-03-08", "recommended_amount": 850000000, "inferred_master": false } ] }

// POST /api/plan
{ "as_of": "2026-03-06", "h": 21, "sl": "p90", "budget": 7000000000 }
// → 200
{ "need_total": 10000000000, "funded_total": 7000000000, "funded_pct": 0.70, "underfunded": 2,
  "visits": [ { "tid": "...", "date": "2026-03-08", "kind": "scheduled|extra|moved",
                "recommended": 850000000, "allocated": 700000000, "override": null,
                "tier1_need": 640000000, "reason": "Below safe minimum on 09 Mar (pre-Lebaran +120%)",
                "flags": ["underfunded"] } ],
  "reallocation": [ { "from_tid": "TID-JKT-0008", "to_tid": "TID-JKT-0007", "amount": 300000000 } ],
  "comparison": { "current": { "cash_out_days": 9, "idle_cash": 0, "idle_cost": 0, "visits": 0, "visit_cost": 0, "loaded": 0 },
                  "recommended": { "...": "same fields" },
                  "replay": { "basis": "true_demand|estimated", "current": {}, "recommended": {} } } }
```

`reallocation` is computed by matching each over-stocked ATM's reduction against the current policy (current load − allocated load, if > 0) with the at-risk ATMs' increases. Matching is greedy, largest first. It is only for the visual; nothing physical moves.

**TR-37**: Write endpoints (`PATCH/POST/DELETE /api/data/log`, `PUT /api/data/master`, `PUT /api/data/holidays`, `POST /api/data/upload`, `POST /api/data/reset`) return:

```json
{ "dataset_version": 4, "issues": [ /* TR-13 */ ], "job": { "job_id": "j_…", "pending_tids": ["TID-JKT-0001"] } }
```

`PATCH /api/data/log` accepts a batch: `{ "rows": [ { "tid", "date", "opening_balance"?, "withdrawal"?, "replenishment"?, "closing_balance"? } ] }`. Missing fields are left unchanged, and the source becomes `edit`.

**TR-38**: `GET /api/status?job_id=` returns `{ "job_id", "done": bool, "total", "finished", "failed": [{tid, error}] }`. Job records are kept in memory for 10 minutes.

## 10. Performance

**TR-39**: Measured on the demo laptop with the dummy data and `WORKERS = cpu_count − 1`:

| Operation | Limit |
|---|---|
| Cold forecast + backtest, all 10 TIDs, one as-of | ≤ 60 s |
| Startup warm-up of 3 scenarios | ≤ 3 min, non-blocking (the UI is usable as soon as the default scenario finishes) |
| One-row edit → that TID ready | ≤ 5 s |
| `GET /fleet`, `POST /plan`, override save (cache warm) | ≤ 300 ms server time |
| `GET /atm/{tid}` (cache warm) | ≤ 300 ms |
| Upload 10 TIDs × 2 years CSV (parse + validate + store) | ≤ 3 s |

**TR-40**: Each worker process sets `OMP_NUM_THREADS = OPENBLAS_NUM_THREADS = MKL_NUM_THREADS = 1`, so the processes don't oversubscribe the CPU.

## 11. Reliability, security, logging

**TR-41**: A failure in one TID (model exception, timeout of 120 s per TID) must not affect other TIDs. The failed TID falls back to `seasonal_naive` with `diagnostics.fallback = true` and is shown in the UI as "fallback model".

**TR-42**: The server binds to `127.0.0.1` only, there is no auth (PRD), and CORS is enabled only in dev mode for `http://localhost:5173`. Uploaded files are parsed in memory and never executed or saved under their original names.

**TR-43**: Logging goes to stdout and `workspace/app.log` (rotating, 5 MB × 3). Each job, fit duration per TID, and every write with its `dataset_version` is logged. Log entries include TIDs and dates only, never full rows.

**TR-44**: Determinism: the same database state + parameters must give byte-identical API responses, apart from `job_id` and timestamps. Sort every list by a stable key.

## 12. Testing & traceability

**TR-45**: Test layout and markers: `backend/tests/{engine,api,perf}`. `pytest -m "not perf"` is the default and must finish in ≤ 3 min; `pytest -m perf` is run manually. Golden tests use the shipped dummy data loaded into a temporary SQLite file (fixture).

| Requirement | Verified by |
|---|---|
| PRD AC1 | `tests/engine/test_generator.py`: run the generator into a temp dir, compare hashes with `data/*.csv`, check the balance identity |
| AC2 | Playwright smoke: all 5 routes render with no console errors |
| AC3 | `test_golden_accuracy.py`: at as-of 2026-03-06, ≥ 7/10 TIDs have chosen-model WAPE < seasonal-naive WAPE (h = 14) |
| AC4 | `test_golden_lebaran.py`: as-of 2026-03-01, h = 21; for TID-TNG-0006 and TID-JKT-0007, the actual peak day's value lies in [q10, q90] |
| AC5 | `tests/api/test_edit_recompute.py`: edit one row → only that TID's cache key changes; ready in ≤ 5 s |
| AC6, AC10 | `tests/api/test_upload.py`: valid, broken, unknown-TID, alias-header, and XLSX files |
| AC7 | `tests/engine/test_allocate.py`: budget = 70% of need → Tier-1 order per TR-32, caps, denomination multiples |
| AC8 | `test_golden_replay.py`: as-of 2026-03-01, h = 30, unconstrained; replay on `true_demand` gives recommended cash-out days < current, and less idle cash for TID-DPK-0004, TID-BKS-0005, TID-JKT-0008 |
| AC9 | Playwright: Pre-Lebaran scenario → ≥ 1 `cash_out_risk` and ≥ 1 `over_stocked`; the planner at 70% shows ≥ 1 reallocation flow |
| TR-16 | `test_true_demand_isolation.py`: static import check + runtime spy confirming forecasting never reads `true_demand` |
| TR-19 | Property test: random demand/loads → identity holds; withdrawals never exceed available cash |
| TR-39 | `tests/perf/*` with timing asserts |

**TR-46**: Before a task is reported as done, `ruff check`, `ruff format --check`, `pytest -m "not perf"`, `npm run lint`, `npm run build`, and `npx vitest run` must pass. If anything was skipped, say so.

## 13. Open technical items

- Quantile-of-sum for cycle need (TR-30) instead of summing daily quantiles. Consider this if the backtests show over-stocking at p90.
- Whether to add a regression + ARIMA-error candidate (PRD §5.3, optional). Add it only if SARIMAX misses the Lebaran check.
- Exact Tailwind theme tokens and chart colours, to be set during UI build.
