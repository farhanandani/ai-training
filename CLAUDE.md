# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status

Local web demo for **ATM cash forecasting & replenishment recommendation**, built to present to a client (bank / ATM fleet operator). The repo holds the specs, the dummy dataset, the FastAPI + engine backend (`backend/`), the React SPA (`frontend/`) and the launch scripts (`scripts/`).

- `docs/PRD.md`: what to build, the formulas (forecast, need, extra visits, budget allocation, comparison), and acceptance criteria AC1–AC10. **This is the source of truth for business logic.**
- `docs/ARCHITECTURE.md`: how to build it: repo layout, heavy/light compute split, cache keys, API table, test strategy.
- `docs/TRD.md`: exact technical requirements with IDs (`TR-01`…`TR-46`): venv setup and dependency versions, file/alias parsing rules, validation codes, SQLite DDL, engine signatures, model and backtest parameters, API payloads, performance limits, and the test ↔ acceptance-criteria matrix. Cite TR IDs in tests and reviews.
- Sections marked **[Claude's call]** in the docs are decisions made by Claude, not by the owner. They can be revisited. Unmarked decisions came from the owner, so don't change them without asking.

The owner talks in Indonesian. The UI and the docs are in English.

## Commands

Backend (Python 3.13, venv at `backend\.venv`; run pytest/ruff from `backend/`) and frontend (Vite + React) both exist now.

```
scriptsun.ps1                    # demo: build SPA if stale, serve everything on 127.0.0.1:8000 (-NoBrowser to skip opening it)
scripts\dev.ps1                    # uvicorn --reload :8000 + vite :5173 (proxies /api)
python data/generate_dummy.py      # regenerate all CSVs in data/ (seeded, byte-for-byte reproducible; stdlib only)

cd backend; pytest                 # default fast suite (excludes slow + perf markers)
cd backend; pytest -m slow         # golden model tests (AC3/AC4)
cd backend; pytest -m perf         # timing tests (TR-45)
cd backend; pytest tests/engine/test_allocate.py::test_name   # single test
cd backend; ruff check .; ruff format --check .

cd frontend; npm run lint
cd frontend; npm test              # vitest run (unit/component)
cd frontend; npm run build         # tsc -b && vite build
cd frontend; npm run e2e           # build + Playwright smoke tests (uvicorn on :8123, fresh temp workspace DB; first run: npx playwright install chromium)
cd frontend; npm run gen:api       # regenerate src/api/schema.d.ts from a running backend on :8000
```

Env overrides use the `CASHFC_` prefix (see `backend/app/settings.py`): `WORKSPACE_DB`, `PORT`, `WARMUP_SCENARIOS`, `WORKERS`, `FRONTEND_DIST`, ...

## Data (`data/`)

- `generate_dummy.py` produces `atm_daily_log.csv` (one row per TID per day, 10 TIDs, 2024-10-28 → 2026-10-27), `atm_master.csv`, `holidays_id.csv` and `atm_true_demand.csv`.
- If you change the generator, re-run it and keep AC1 true (identical output across runs). Re-check the demo-critical properties PRD §4.4 describes:
  - cash-out days are concentrated around Lebaran and year-end;
  - hospital, campus and residential ATMs are over-stocked (>30% of capacity left at each visit);
  - the balance identity `closing = opening − withdrawal + replenishment` holds on every row.
- `atm_true_demand.csv` is dummy-only ground truth: demand before it was capped by an empty ATM. It may be used **only** to replay and score plans in time-travel mode (`compare.py`). It must never be used for model fitting or backtest scoring.
- The 2026 Islamic holiday dates are approximate.

## Architecture invariants (span multiple modules)

- **Heavy vs light layer.**
  - Heavy: model fit, backtest and forecast. It runs per TID in a ProcessPool and is cached in SQLite.
  - Light: schedule, projection, recommendation, allocation and comparison. These are pure functions that run on every request.
  - Budget, service level, overrides, horizon (≤ 30) and master-constraint changes must never trigger a refit.
- **Forecasts are always 30 days.** Backtests also run at H = 30, and a shorter H is a slice. That is why the horizon is not part of the cache key.
- **Cache key** = (tid, as_of, hash of that TID's rows ≤ as_of, holiday hash, `ENGINE_VERSION`). Bump `ENGINE_VERSION` whenever model code changes.
- **`engine/` never imports `app/`.** The engine does no I/O and uses no globals: it takes DataFrames/dataclasses and returns them, so it runs in worker processes.
- **Censoring:** days with `closing_balance = 0` (cash-out) and out-of-service days are set to NaN for fitting and excluded from accuracy metrics.
- **Money is integer IDR** everywhere outside the models. Amounts are rounded to the ATM's `denomination` and capped at `capacity`.
- **Balance simulation:** `plan.py` and `compare.py` must share one balance-simulation function, so the plan and the replay of a plan cannot disagree.
- **Validation:** it reports problems and never silently fixes data. Edits that break the balance identity are saved with a warning. A log with an unknown TID gets an auto-inferred master row flagged `inferred`.
