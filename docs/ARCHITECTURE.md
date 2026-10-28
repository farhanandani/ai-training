# Architecture — ATM Cash Forecasting & Replenishment Demo

| | |
|---|---|
| **Status** | Draft v1 — for review |
| **Date** | 2026-10-28 |
| **Implements** | [`docs/PRD.md`](PRD.md) |

This document explains how the PRD is built: the components, how data moves through them, and the rules that keep the demo fast and correct. The PRD defines *what* to build and the formulas. This document does not repeat them; it points to PRD sections (§) instead.

---

## 1. System overview

One local process serves both the API and the built web UI. It runs only on the presenter's laptop and needs no internet.

```
 Browser (React SPA)                         Python process (uvicorn, 127.0.0.1:8000)
┌──────────────────────┐   HTTP/JSON   ┌───────────────────────────────────────────────┐
│ Fleet · ATM Detail   │ ────────────► │ app/  FastAPI                                  │
│ Planner · Data Editor│ ◄──────────── │   routes  →  services  →  engine (pure Python) │
│ Accuracy             │   poll status │                │                 │            │
└──────────────────────┘               │          JobRunner         Forecast cache     │
                                       │   (ProcessPool, per TID)    (SQLite)          │
                                       │                │                              │
                                       │          Workspace store (SQLite)             │
                                       └────────────────┬──────────────────────────────┘
                                                        │ seed on first run / "Reset"
                                                  data/*.csv (dummy, read-only)
```

**Two compute layers.** This split is the main design decision.

| Layer | What | When it runs | Cost |
|---|---|---|---|
| **Heavy**: forecasting | Preprocess → fit candidate models → backtest → select → forecast p10/p50/p90 | When a TID's data, holidays, or the as-of date changes | Seconds per TID, run in a background process pool, cached |
| **Light**: planning | Schedule → projection → recommendation → extra visits → allocation → comparison → overrides | On every request | Milliseconds, pure functions over the cached forecast |

Changing the budget, service level, overrides, the horizon (≤ 30), or master constraints **never refits a model**. That is how the PRD §8 targets are met: ≤ 300 ms for planner changes, ≤ 5 s for a one-row edit.

## 2. Repository layout

```
D:\Training\
├─ data/                     # Seed dataset (dummy), generator — read-only at runtime
│  ├─ generate_dummy.py
│  ├─ atm_daily_log.csv  atm_master.csv  holidays_id.csv  atm_true_demand.csv
├─ backend/
│  ├─ pyproject.toml         # deps + pytest config
│  ├─ engine/                # Pure domain logic. Imports pandas/numpy/statsmodels only.
│  │  ├─ schema.py           # Column names, dtypes, dataclasses (AtmMaster, Visit, PlanResult…)
│  │  ├─ ingest.py           # CSV/XLSX → DataFrame, column mapping, derive withdrawal/replenishment
│  │  ├─ validate.py         # PRD §4.1 rules → list[Issue]; infer master rows for unknown TIDs
│  │  ├─ preprocess.py       # Censoring (cash-out / out-of-service → NaN), daily reindex
│  │  ├─ calendar.py         # Holiday table → exogenous feature matrix (PRD §5.2)
│  │  ├─ models/
│  │  │  ├─ base.py          # Model protocol: fit(y, X) / predict(h, X_future) -> quantiles
│  │  │  ├─ seasonal_naive.py
│  │  │  ├─ ets.py           # Holt-Winters / ETS on log demand
│  │  │  └─ sarimax.py       # SARIMAX + calendar exog, small AIC grid
│  │  ├─ backtest.py         # Rolling-origin backtest, WAPE/MAPE/MAE/coverage, Lebaran check
│  │  ├─ forecast.py         # Per-TID pipeline: select model → final fit → 30-day forecast
│  │  ├─ schedule.py         # Infer cycle phase / next_visit_date (PRD §6.1)
│  │  ├─ plan.py             # Projection, status, need, extra visits, skip/merge (PRD §6.1–6.2)
│  │  ├─ allocate.py         # Budget allocation, tiers, re-projection (PRD §6.3)
│  │  └─ compare.py          # Current vs recommended, replay against actuals (PRD §6.4)
│  ├─ app/                   # FastAPI layer — no domain logic here
│  │  ├─ main.py             # App factory, static file mount for the built SPA
│  │  ├─ settings.py         # Paths, workers, default scenario
│  │  ├─ store.py            # Workspace SQLite access (data, master, holidays, overrides, cache)
│  │  ├─ jobs.py             # JobRunner: ProcessPoolExecutor, job registry, dedupe by cache key
│  │  ├─ services.py         # Orchestrates engine calls; computes data hashes / cache keys
│  │  ├─ dto.py              # Pydantic request/response models
│  │  └─ routes/             # fleet.py, atm.py, planner.py, data.py, accuracy.py, system.py
│  └─ tests/
│     ├─ engine/             # Unit + golden tests on the dummy data
│     └─ api/                # FastAPI TestClient tests
├─ frontend/
│  ├─ package.json  vite.config.ts  tsconfig.json
│  └─ src/
│     ├─ main.tsx  App.tsx  routes.tsx
│     ├─ api/                # Typed fetch client + TanStack Query hooks
│     ├─ state/              # Zustand store: asOf, horizon, serviceLevel, scenario
│     ├─ pages/              # FleetOverview, AtmDetail, Planner, DataEditor, Accuracy
│     ├─ components/         # Header, StatusBadge, KpiTile, BalanceGauge, charts/, grid/
│     └─ lib/format.ts       # Rp formatting, dates
├─ workspace/                # Runtime state (gitignored): workspace.db
├─ scripts/
│  ├─ run.ps1                # Build SPA if stale, start uvicorn — the one demo command
│  └─ dev.ps1                # uvicorn --reload + vite dev server (proxy /api)
└─ docs/  PRD.md  ARCHITECTURE.md
```

**Dependency rule:** `engine` never imports `app`. Everything in `engine` takes DataFrames and dataclasses and returns DataFrames and dataclasses. No I/O, no globals. That keeps it testable and lets it run in worker processes.

## 3. Technology choices

| Concern | Choice | Why |
|---|---|---|
| Python | 3.13 (installed) | statsmodels ≥ 0.14.4 supports it |
| Engine libs | pandas, numpy, statsmodels, scipy | Classic statistical models with prediction intervals; no deep learning (PRD §5.3) |
| API | FastAPI + uvicorn + Pydantic v2 | Typed DTOs and auto OpenAPI docs, which the frontend types are generated from |
| Upload parsing | python-multipart, openpyxl | CSV + XLSX upload |
| Storage | SQLite (stdlib `sqlite3`) | Single file, survives restarts, no server; small data (≈7k rows per 10 TIDs) |
| Parallelism | `concurrent.futures.ProcessPoolExecutor` | Model fits are CPU-bound; one TID per task |
| Frontend | React 18 + Vite + TypeScript | |
| Server state | TanStack Query | Caching, refetch after mutations, polling job status |
| UI state | Zustand | Global controls (as-of, horizon, service level, scenario) |
| Charts | ECharts (`echarts-for-react`) | dataZoom, bands (stacked areas), markArea for holidays, Sankey for re-allocation |
| Data grid | AG Grid Community | Inline edit, pagination, filtering on ~7k+ rows |
| Styling | Tailwind CSS | Fast, consistent, no runtime |
| API types | `openapi-typescript` | Frontend types generated from FastAPI's `/openapi.json` |
| Tests | pytest, httpx TestClient; Vitest; Playwright (one smoke test) | |

All JS/CSS/fonts are bundled at build time. Nothing is loaded from a CDN at runtime, so the demo works offline.

## 4. Data & storage

### 4.1 Workspace database (`workspace/workspace.db`)

| Table | Key | Content |
|---|---|---|
| `daily_log` | (`tid`, `date`) | PRD §4.1 columns + `source` (`dummy`/`upload`/`edit`) |
| `atm_master` | `tid` | PRD §4.2 columns + `inferred` flag |
| `holidays` | `date` | PRD §4.3 |
| `true_demand` | (`tid`, `date`) | Dummy ground truth only. **Never read by forecasting code** (enforced by only `compare.py` receiving it) |
| `overrides` | (`tid`, `visit_date`) | Manual visit edits (date, amount, skipped) |
| `settings` | `key` | Budget, idle-cash rate, over-stock threshold, data-source label |
| `forecast_cache` | `cache_key` | Serialized per-TID forecast + backtest result (JSON) |
| `dataset_meta` | — | `dataset_version` (incremented on every data change) |

**Seeding:** on first start, or when the user clicks **Reset to dummy data**, the tables are filled from `data/*.csv` and `overrides` and `forecast_cache` are cleared.

Monetary values are stored and computed as **integers (IDR)** everywhere except inside the models. Model output is rounded at the boundary.

### 4.2 Cache keys

```
tid_data_hash   = sha256(rows of daily_log for TID with date ≤ as_of)
holiday_hash    = sha256(holidays table)
cache_key       = sha256(tid, as_of, tid_data_hash, holiday_hash, ENGINE_VERSION)
```

- The forecast is always produced for **30 days** (the max horizon) and backtested at **H = 30**. Metrics for a smaller H are computed by slicing the first H days. So **changing the horizon never refits.**
- Editing a row on date *d* only changes the hash of that TID, and only for as-of dates ≥ *d*. Other TIDs stay cached (PRD AC5).
- `ENGINE_VERSION` is bumped whenever model code changes, which invalidates old results.
- Master constraints are **not** part of the key, because they affect planning only.

## 5. Forecast pipeline (heavy layer)

Per TID, inside one worker process (`engine/forecast.py::run_tid`):

```
log rows ≤ as_of ─► preprocess ─► y (daily demand, NaN on censored days)
holidays ───────► calendar ───► X (history) , X_future (as_of+1 … as_of+30)
                                      │
               ┌──────────────────────┴───────────────────────┐
               ▼                                              ▼
  order selection (SARIMAX AIC grid,             backtest: 8 origins × 14 days apart,
  once, on full history)  ──── orders reused ──► each candidate re-fit on data < origin,
                                                 forecast 30 d, score vs y (non-censored)
                                                 + Lebaran check origin (if in range)
                                                              │
                                     select candidate with lowest WAPE (PRD §5.4)
                                                              │
                         final fit of the winner on all data ≤ as_of → 30-day p10/p50/p90
                         + feature contributions for explanations (PRD §5.5)
```

Implementation rules:
- **Log transform:** fit on `log1p(demand)`. Quantiles are transformed back with `expm1`, which is valid for quantiles. Use the p50 quantile, not the back-transformed mean.
- **Missing values (NaN):** SARIMAX handles them natively through the Kalman filter. For ETS, fill censored days with the seasonal-naive value for fitting only. They are never scored.
- **Seasonal naive intervals:** empirical quantiles of the residuals from 7 days earlier.
- **Orders:** select once per (TID, as_of), then reuse them across backtest origins. This keeps the fit count around 10 TIDs × (grid + 8 origins × 3 models + 1).
- **Determinism:** fixed grids, fixed optimizer settings (`method="lbfgs"`, `maxiter` set), no random seeds needed. Convergence warnings are caught and recorded as model diagnostics. If SARIMAX fails, that candidate is skipped and the TID still gets a forecast.
- **Explanations:** the SARIMAX exogenous coefficients give per-day uplift percentages (e.g. "pre-Lebaran +85%"). If ETS or naive wins, the explanation instead compares with the same weekday of the last 4 weeks.

**Performance budget** (10 TIDs, 2 years, about 8 cores): about 60 s for a cold run. Mitigations:
1. Run TIDs in parallel.
2. Cap the SARIMAX grid: p,q ∈ {0,1,2}, P,Q ∈ {0,1}, d = 1 or 0 by ADF test, D = 0. Keep the best 3 by AIC on the full history; the backtest uses the single best.
3. **Warm-up at startup:** pre-compute the three demo scenarios (PRD §6.1), so the presenter never waits for the first screen.

## 6. Planning pipeline (light layer)

`services.plan(as_of, horizon, service_level, budget)` runs synchronously on every request:

```
forecast (cached, 30 d) ─┐
master constraints ──────┼─► schedule.visits()   (next_visit_date or inferred phase)
balance at as_of ────────┤        │
overrides ───────────────┘        ▼
                       plan.project_current()      → current-policy projection + status
                       plan.recommend()            → need per visit, skip, extra visits, merge
                       allocate.allocate(budget)   → tiered, date-ordered, re-projected
                       plan.apply_overrides()      → manual edits win, re-project
                       compare.summary()           → KPIs (PRD §6.4); replay vs actuals when
                                                     as_of < last date (true_demand if present)
```

- All functions are pure, take numpy arrays per TID, and are vectorized over the horizon. Target: ≤ 50 ms for 10 TIDs.
- **Truncation to H:** projection and allocation use only days `as_of+1 … as_of+H`.
- **Replay mode:** `compare.replay(plan, actual_demand)` re-simulates the balance day by day. Withdrawals are capped by the available balance, using the same rules as the generator. The function counts cash-out days, idle cash, and visit cost for both plans.

## 7. Jobs & recompute flow

`app/jobs.py` holds one `ProcessPoolExecutor` (workers = `cpu_count − 1`) and an in-memory registry keyed by `cache_key`. If a key is already running, the request joins that job instead of starting a new one.

```
UI action (upload / edit / as-of change)
  → API writes data (if any), bumps dataset_version
  → services.ensure_forecasts(as_of): for each TID compute cache_key
       hit  → ready
       miss → submit run_tid(...) to the pool
  → response: { ready_tids, pending_tids, job_id }
UI polls GET /api/status?job_id=… every 500 ms (TanStack Query refetchInterval)
  → as TIDs finish, their views refresh; the header spinner shows "Forecasting 3/10"
```

- Planner endpoints return results for the ready TIDs, and list the TIDs still pending, so the UI is never blocked.
- If a newer `dataset_version` appears while a job is running, the job's result is still cached under its own key. It is simply not the current key any more, so nothing is wrong.
- Worker errors are stored per TID and shown on the Accuracy page and the ATM card ("Forecast failed: …"). The other TIDs keep working.

## 8. API (all under `/api`, JSON)

| Method & path | Purpose | Layer |
|---|---|---|
| `GET /context` | Data source label, min/max date, TID list, scenarios, defaults | — |
| `GET /fleet?as_of&h&sl` | KPI tiles + one row per TID (balance, days left, status, next visit, recommended amount) | light |
| `GET /atm/{tid}?as_of&h&sl&from` | History, forecast quantiles, projections (current/recommended), visits, explanation, model + metrics, actual overlay | light |
| `POST /plan` | Body: as_of, h, sl, budget → allocation table, re-allocation flows, comparison | light |
| `PUT /plan/overrides` / `DELETE /plan/overrides` | Save/clear manual visit edits | light |
| `GET /plan/export.csv` | `tid, visit_date, amount, source` | light |
| `GET /accuracy?as_of&h` | Per-TID model table, candidate metrics, backtest series | cached heavy |
| `GET /data/log?tid&from&to&page` · `PATCH /data/log` · `POST /data/log` · `DELETE /data/log` | Grid read and row edits (batch) | write → heavy |
| `GET/PUT /data/master` · `GET/PUT /data/holidays` | Master / holiday edits | write |
| `POST /data/upload` (multipart: file, kind=log\|master\|holidays, mode=replace\|merge) | Upload, return validation issues | write → heavy |
| `GET /data/validation` | Current issue list (PRD §4.1) | — |
| `GET /data/download?kind=` | Download the current data as CSV | — |
| `POST /data/reset` | Restore dummy data | write → heavy |
| `GET /status?job_id` | Job progress per TID | — |

**Write semantics:** every write returns `{dataset_version, issues[], job}`. An edit that breaks the balance identity is **saved, with a warning** (PRD: show, never silently fix). Upload rows that cannot be parsed are rejected and returned as issues; the rest are saved.

## 9. Frontend

- **Routing:** `/` Fleet · `/atm/:tid` · `/planner` · `/data` · `/accuracy`.
- **Global header:** a scenario preset select, as-of date picker (bounded to the data range), horizon slider (7–30), service level select (p50/p80/p90/p95), data source badge, and recompute progress. The values live in Zustand **and in the URL query string**, so a demo view can be bookmarked and reloaded.
- **Data fetching:** one TanStack Query hook per endpoint. Query keys include `(as_of, h, sl, dataset_version)`. Mutations invalidate by `dataset_version`.
- **Charts** (`components/charts/`):
  - `DemandForecastChart`: actual bars or line, p50 line, a p10–p90 band (two stacked areas), holiday `markArea` with Lebaran labelled, and a dashed actuals overlay after the as-of date.
  - `BalanceChart`: actual balance with markPoint on replenishments, current vs recommended projections, a `min` markLine, and visit markers.
  - `ReallocationSankey`: over-stocked TIDs → at-risk TIDs.
  - `BacktestChart`.
- **Planner:** AG Grid with editable `visit_date`/`amount`/`skip` cells. Edits are debounced by 300 ms → `PUT /plan/overrides` → refetch `POST /plan`.
- **Data Editor:** AG Grid with server-side pagination (via the API page params), batch save, an upload dialog (kind + mode), a validation panel, and Reset/Download buttons.
- **Formatting:** `Intl.NumberFormat('id-ID')` for `Rp 640.000.000`, a compact form `Rp 640 jt` / `Rp 1,2 M` for tiles, and English dates `12 Mar 2026` (PRD §7).
- **Look:** a clean light theme fit for a client meeting. Status colours: cash-out risk = red, over-stocked = amber, OK = green, and every badge also has a text label.

## 10. Running

| Mode | Command | What happens |
|---|---|---|
| Demo | `scripts\run.ps1` | Create/refresh `.venv`, `pip install -e backend` (first time), `npm ci && npm run build` if `frontend/dist` is stale, then `uvicorn app.main:app --host 127.0.0.1 --port 8000`, and open the browser. FastAPI serves `frontend/dist` at `/`. |
| Dev | `scripts\dev.ps1` | `uvicorn --reload` on :8000 + `vite` on :5173 with `/api` proxied. |

First-time setup needs internet (pip/npm). After that, the demo runs fully offline.

## 11. Testing strategy

| Level | What | Maps to |
|---|---|---|
| Engine unit | `validate` rules, `preprocess` censoring, `calendar` features on known dates, `schedule` phase inference (emergency refills ignored), `plan` need/skip/extra-visit/merge on hand-built cases, `allocate` tiers + caps + denomination, `compare.replay` | PRD §4–6 |
| Engine golden | Dummy data, as-of 2026-03-01: ≥ 7/10 TIDs beat seasonal naive; terminal/airport p10–p90 contains the actual peak; recommended < current on cash-out days (replayed on `true_demand`) | AC3, AC4, AC8 |
| Generator | Byte-for-byte reproducibility; balance identity | AC1 |
| API | Upload valid/broken/unknown-TID files; edit one row → only that TID's cache key changes; budget 70% → tier order respected | AC5, AC6, AC7, AC10 |
| Performance | Cold full run ≤ 60 s; one-row edit ≤ 5 s; `/plan` ≤ 300 ms (pytest timing marks, run manually) | PRD §8 |
| E2E smoke | Playwright: open app → Pre-Lebaran scenario shows ≥1 risk + ≥1 over-stock → Planner budget 70% shows re-allocation | AC2, AC9 |

## 12. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Only two Lebaran events in history, so the Lebaran coefficients are uncertain | Bucketed `days_to_idul_fitri` features (fewer parameters), wider intervals in the window, and a separate Lebaran-check metric shown honestly |
| SARIMAX is slow or fails to converge | Capped grid, reused orders, parallel per TID, warm-up cache, fallback to ETS/naive |
| Client log format differs (column names, intraday rows) | An `ingest.py` column-mapping step and daily aggregation (PRD §10). Validation reports issues instead of crashing |
| Planning logic and replay drift apart | One shared `simulate_balance()` function, used by both `plan.py` and `compare.py` |
| Approximate 2026 Islamic holiday dates | The holiday table is editable; verify against the SKB before the client demo (PRD §10) |

## 13. Decisions log

All of these are **[Claude's call]** unless stated otherwise.
1. One process (FastAPI serves the SPA) instead of separate servers. This gives the simplest demo start.
2. The split into a heavy forecasting layer and a light planning layer, with the forecast always computed for 30 days.
3. SQLite workspace instead of in-memory state, so edits survive a restart during the meeting.
4. ProcessPool + polling instead of Celery/Redis/WebSockets. That avoids extra infrastructure on a laptop.
5. ECharts instead of Recharts, for bands, zoom, markArea, and Sankey in one library.
6. AG Grid Community for the data editor.
7. Warm-up of the demo scenarios at startup.
