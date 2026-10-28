# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status

Local web demo for **ATM cash forecasting & replenishment recommendation**, built to present to a client (bank / ATM fleet operator). At the moment the repo holds only the specs and the dummy dataset. `backend/`, `frontend/` and `scripts/` are planned and do not exist yet.

- `docs/PRD.md`: what to build, the formulas (forecast, need, extra visits, budget allocation, comparison), and acceptance criteria AC1–AC10. **This is the source of truth for business logic.**
- `docs/ARCHITECTURE.md`: how to build it: repo layout, heavy/light compute split, cache keys, API table, test strategy.
- `docs/TRD.md`: exact technical requirements with IDs (`TR-01`…`TR-46`): venv setup and dependency versions, file/alias parsing rules, validation codes, SQLite DDL, engine signatures, model and backtest parameters, API payloads, performance limits, and the test ↔ acceptance-criteria matrix. Cite TR IDs in tests and reviews.
- Sections marked **[Claude's call]** in the docs are decisions made by Claude, not by the owner. They can be revisited. Unmarked decisions came from the owner, so don't change them without asking.

The owner talks in Indonesian. The UI and the docs are in English.

## Commands

Commands that work today (Python 3.13; the generator uses the stdlib only):

```
python data/generate_dummy.py      # regenerate all CSVs in data/ (seeded, byte-for-byte reproducible)
```

Planned commands, from ARCHITECTURE.md §10–11, available once scaffolded:

```
scripts\run.ps1                    # demo: build SPA if stale, serve everything on 127.0.0.1:8000
scripts\dev.ps1                    # uvicorn --reload :8000 + vite :5173 (proxies /api)
cd backend; pytest                 # all backend tests
cd backend; pytest tests/engine/test_allocate.py::test_name   # single test
cd frontend; npm run build / npx vitest
```

numpy, pandas and statsmodels are **not** installed globally yet. The backend will need a `.venv`.

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
