# PRD — ATM Cash Forecasting & Replenishment Demo

| | |
|---|---|
| **Status** | Draft v1 — for review |
| **Date** | 2026-10-28 |
| **Owner** | Muhammad Andani |
| **Audience** | Client presentation (bank / ATM fleet operator) |
| **UI language** | English |

Items marked **[Claude's call]** were decided while writing this document, not by the owner. They can be changed.

---

## 1. Overview & problem

The client runs a fleet of ATMs and replenishes each one on a **fixed cycle** (every N days), topping it up to a **fixed fill level**. Because the amount does not follow real demand, they get both kinds of failure:

- **Cash-out**: an ATM runs empty before its next scheduled visit. This happens most around paydays, the weeks before Lebaran, and the year-end. The result is lost transactions, unhappy customers, and costly emergency CIT visits.
- **Idle cash**: an ATM still holds a large balance when the scheduled visit arrives. Money is tied up in the machine when it could be used elsewhere, and the visit itself was partly unnecessary.

This product is a **local web demo** that reads **daily ATM balance logs** (one row per TID per day), forecasts withdrawals per ATM with a statistical engine in Python, and recommends **when** and **how much** to replenish each ATM. When the client's cash budget is limited, it moves money from ATMs that will be over-stocked to ATMs that will run short ("cross-subsidy"). **The system only recommends. The client makes the final decision** and can override every number.

## 2. Goals, non-goals, anti-goals

### Goals
1. Accurate per-ATM daily withdrawal forecasts. Accuracy must be measured and shown (backtest MAPE/MAE), not just claimed.
2. Per-ATM recommendation for the planning horizon: visit date(s), amount, and the reason (e.g. "projected to fall below safe minimum on 14 Mar").
3. Allocation of a **user-entered total budget** across ATMs. Shortfalls go to the most urgent ATMs first. Over-stocked ATMs are reduced or skipped.
4. **Dynamic data**: users can upload their own daily log (CSV/Excel) or edit rows in a table. Forecasts and recommendations recompute automatically.
5. A side-by-side comparison with the client's **current static policy**, so the value is visible in IDR, cash-out days, and visits.

### Non-goals
- No login, users, or roles.
- No live integration with bank/switch/CIT systems. Data comes in by file or table edit only.
- No physical transfer of cash between machines. "Cross-subsidy" means re-allocating the **budget** for the next refills.
- No automatic execution or dispatch of CIT orders.
- No per-denomination cassette mix (a single denomination step per ATM is enough).
- No cloud deployment. It runs on the presenter's laptop.

### Anti-goals (failure even if it "works")
- Recommendations that can't be explained: every number must trace back to the forecast, the constraint, and the rule that produced it.
- An accuracy figure that looks good only because it was measured on training data.
- Recompute that is so slow it breaks the live demo flow (see §8).
- A UI that reads as a dev tool instead of something a cash-management head would use.

## 3. Users & demo story

**User:** the client's cash-management / ATM operations staff, and the presenter driving the demo.

**Demo walkthrough (the story the UI must support):**
1. **Fleet Overview** (opens on the *Pre-Lebaran 2026* scenario): 10 ATMs, each with a status badge: *Cash-out risk*, *Over-stocked*, or *OK*. The badge shows days of cash left and the next scheduled visit.
2. Click an ATM to open **ATM Detail**. It shows the history (with the sudden replenishment jumps visible), then the forecast with an uncertainty band and the projected balance hitting the safe minimum.
3. **Time travel**: set the "as-of date" back to e.g. **2026-03-01**. The engine forecasts the Lebaran 2026 surge, and the actual data is overlaid so the client can see the forecast was right.
4. **Allocation Planner**: enter a total budget smaller than the total need. Cash moves from over-stocked ATMs (hospital, campus, residential) to cash-out-risk ATMs (terminal, airport, mall). Show the comparison with the current policy.
5. **Data Editor**: upload the client's own file, or change a few rows. Everything recomputes.
6. **Accuracy**: backtest MAPE/MAE per ATM and the model chosen for each.

## 4. Data model & input

### 4.1 Daily log: `atm_daily_log` (one row = one TID × one day)

| Column | Type | Required | Notes |
|---|---|---|---|
| `tid` | string | yes | Terminal ID, e.g. `TID-JKT-0001` |
| `date` | date `YYYY-MM-DD` | yes | One row per TID per date |
| `opening_balance` | int IDR | yes | Balance at start of day |
| `withdrawal` | int IDR | yes* | Cash dispensed that day |
| `replenishment` | int IDR | yes* | Cash loaded that day (0 if none) |
| `closing_balance` | int IDR | yes | End-of-day balance |

\* If `withdrawal` and/or `replenishment` are missing, the engine **derives them from balance jumps**. A day where `closing − opening` is larger than +X% of capacity (default 20%) is marked as a replenishment day. On that day, replenishment = `closing − opening + estimated withdrawal`, where the estimate is the median of the same weekday over the last 4 weeks. On all other days, withdrawal = `opening − closing`. **[Claude's call]**

**Validation (on upload and on every edit)**: show results to the user, never silently fix data:
- `closing = opening − withdrawal + replenishment` (tolerance Rp 0). Rows that fail are shown as warnings.
- No negative values. No duplicate (`tid`, `date`) pairs.
- Missing dates per TID are reported. The engine treats them as missing, not as zero.
- `opening(d) ≠ closing(d−1)` is reported as a continuity warning.
- Unknown TID (not in master) → the row is **not** rejected. A master row is **auto-created with inferred values** and flagged "inferred – please review". The values are: `capacity` = max observed balance rounded up to Rp 50 jt; `min_safe_balance` = 1 day of median withdrawal; `replenish_cycle_days` = median gap between scheduled refills; `current_fill_level` = median balance right after a refill; `denomination` = 100 000; `cost_per_visit` = fleet median. **[Claude's call]**

**Upload flow:** the user can upload the log alone (master is inferred as above), or the log and master together. A master upload replaces master rows by `tid`. A log upload in **Replace** mode clears all TIDs not present in the file, including their master rows. Holidays are kept unless a new holiday file is uploaded.

### 4.2 ATM master: `atm_master` (one row per TID)

| Column | Notes |
|---|---|
| `tid`, `location_name`, `location_type` | Identity |
| `capacity` | Max cash the cassettes can hold (IDR) |
| `min_safe_balance` | Below this the ATM is "at risk" |
| `replenish_cycle_days` | Fixed visit cycle (current schedule) |
| `denomination` | Refill rounding step (50 000 or 100 000) |
| `cost_per_visit` | CIT cost per replenishment visit (IDR) |
| `current_fill_level` | The static level the client tops up to today (baseline policy) |
| `next_visit_date` | *Optional.* Anchor for the fixed schedule. If empty, it is inferred (§6.1) |

All master fields can be edited in the UI.

### 4.3 Holiday calendar: `holidays_id` (`date, name, type`)

Types: `new_year`, `christmas`, `idul_fitri`, `cuti_bersama`, `national`. The calendar can be edited and uploaded. It must contain **future** dates covering the forecast horizon, because they drive the regressors. 2026 Islamic dates are approximate. **[Claude's call]**

### 4.4 Dummy dataset (shipped, default)

Generated by `data/generate_dummy.py` (stdlib only, seeded, reproducible):
- **Period** 2024-10-28 → 2026-10-27 (730 days), **10 TIDs, 7 300 rows**. It covers New Year 2025/2026, Christmas, Lebaran 2025 (31 Mar) and Lebaran 2026 (20 Mar), and other national holidays.
- **Location types**: mall, office, traditional market, campus, residential, airport, bus terminal, hospital, industrial estate, tourist area. Each type has its own weekly profile, payday sensitivity, and holiday response.
  - The pre-Lebaran ramp peaks at 1.3–3.2× normal; bus terminal and airport ATMs peak highest (mudik). Office, industrial, and campus ATMs drop on holidays. Mall and tourist ATMs spike at year-end. Ramadan and THR give an extra uplift.
- **Replenishment**: scheduled top-ups to `current_fill_level` every `replenish_cycle_days`. These show as sudden balance jumps. Emergency refills sometimes happen the day after an ATM nearly empties.
- **Both failure modes are built in.** There are 161 cash-out days in total (closing = 0), concentrated in the Lebaran/Ramadan and year-end windows. **Hospital, campus, and residential** ATMs have **40–47% of capacity** left at each scheduled visit (over-stocked). The other ATMs have 14–20% left, and the busy ones run out.
- About 0.4% of days are out-of-service days (withdrawal 0), and about 1% are random demand spikes, to test robustness.
- `data/atm_true_demand.csv` (`tid, date, true_demand`) is **dummy-only ground truth**: the simulated demand before it was capped by an empty ATM. It is used **only** to score plans in time-travel mode (§6.4). The engine must never fit on it. Real client data will not have it.

## 5. Forecast engine (Python)

### 5.1 Target
Daily **true demand** per TID. **Cash-out days are censored**: if `closing_balance = 0`, the observed withdrawal is lower than real demand. Out-of-service days (withdrawal 0 with balance available) are also not real demand. Both are marked as missing (`NaN`) for model fitting and excluded from accuracy scoring. **[Claude's call]** This matters for accuracy: training on capped values teaches the model to under-forecast exactly at peaks.

### 5.2 Calendar features (exogenous regressors, known in advance)
- Day of week (one-hot)
- Payday window (day ≥ 25 or ≤ 3)
- `days_to_idul_fitri` buckets: Ramadan 30–21, THR 20–11, ramp 10–1, holiday + cuti bersama 0 to −6, return −7 to −13
- Year-end window (20–31 Dec), New Year's Day
- Day before a national holiday; national holiday / cuti bersama day
- Linear trend

### 5.3 Candidate models (per TID) **[Claude's call]**
1. **Seasonal naive** (value from 7 days earlier). This is the baseline; anything chosen must beat it.
2. **Holt-Winters / ETS** with weekly seasonality, on log demand.
3. **SARIMAX** on log demand with weekly seasonality (s = 7) and the calendar regressors above. Orders are chosen by a small AIC grid search.
4. *(Optional, if time allows)* **Regression + ARIMA errors**: OLS/ridge on the calendar features, with ARIMA on the residuals.

Libraries: `pandas`, `numpy`, `statsmodels`. No deep learning.

### 5.4 Model selection & backtest
- **Rolling-origin backtest**: the last 8 origins, spaced 14 days apart, with horizon = the selected horizon H. The model is re-fit at each origin using only data before it, so there is no leakage.
- **Metrics**: MAPE (excluding zero/censored actuals), MAE (IDR), and WAPE. **The model with the lowest WAPE is selected per TID** **[Claude's call]**. WAPE is used for selection because it is stable when some days are small. MAPE and MAE are shown because the client asked for them.
- Also report the **accuracy of the P10–P90 interval** (% of actuals inside the band).
- **Lebaran check**: a separate backtest with origin = 14 days before Lebaran 2026, reported on its own. A model must not be chosen only because it does well on quiet periods.

### 5.5 Output
For each TID and each day in the horizon: `p50` (point forecast), `p10`, `p90`, model name, and the feature contributions used in explanations (e.g. "pre-Lebaran +85%").

### 5.6 Recompute triggers
Recompute after an upload, a row edit, a master/holiday edit, an as-of date change, or a horizon change. Only the affected TIDs are re-fit. Results are cached per (TID, data hash, as-of date, horizon).

## 6. Replenishment recommendation & budget allocation

Notation for one ATM at as-of date **T** (all forecasts made with data ≤ T):
`B₀` = closing balance at T; `f(d)` = forecast demand on day d; `min` = min_safe_balance; `cap` = capacity; `c` = cycle days; `step` = denomination.

### 6.1 Projected balance & status
- **Scheduled visits**: use `next_visit_date` if it is set. Otherwise infer the schedule phase from the log: take all replenishment dates in the last 90 days, compute `date mod c`, and use the **most common phase**. This way emergency refills, which are off-phase, are ignored. Then project every `c` days through the horizon. The user can edit the schedule in the planner. **[Claude's call]**
- Project the balance under the **current policy** (top up to `current_fill_level` on each visit) using `p50` and `p90` demand.
- **Status**
  - **Cash-out risk**: the p90 projected balance falls below `min` before the next scheduled visit.
  - **Over-stocked**: at the next scheduled visit, the p50 projected balance is more than **30% of `cap`**. The threshold is configurable. With the dummy data this flags hospital, campus, and residential. **[Claude's call]**
  - **OK**: otherwise.
- *Days of cash left* = days until the p50 projected balance falls below `min`.
- **Demo scenarios** **[Claude's call]**: preset buttons in the header set the as-of date and horizon in one click. *Today* = last date in data, H 14. *Pre-Lebaran 2026* = as-of 2026-03-06, H 21. *Year-end 2025* = as-of 2025-12-15, H 21. The app opens on **Pre-Lebaran 2026**, so the first screen already shows both cash-out risk and over-stock.

### 6.2 Recommended amount per visit
For a visit on day `v`, with the following visit at `v + c`:

```
need(v) = Σ_{d=v}^{v+c-1} q(d)  +  min  −  projected_balance_before_visit(v)
amount  = clamp( roundUp(need, step), 0, cap − projected_balance_before_visit(v) )
```

`q(d)` = the demand quantile for the chosen **service level** (default p90; the slider offers p50/p80/p90/p95). **[Claude's call]**

- If `amount = 0` → recommend **Skip visit**. This saves `cost_per_visit`.
- **Extra visits (owner's decision):** the engine may add **as many extra (unscheduled) visits as needed**: on consecutive days, on holidays, and during cuti bersama. **Every visit's cost is shown** so the client can weigh it. The procedure walks forward day by day using the p_service projection. When the balance would fall below `min` before the next visit, insert an extra visit on that day (morning load), sized by the same `need` formula up to the next visit, capped at `cap`. Repeat until the horizon is covered. This handles peaks where a full machine only covers ~1.5–2 days. Extra visits are labelled "Extra" with the reason.
- **Merge visits**: if skipping visit *k* and adding its amount to visit *k−1* stays within capacity without a breach, suggest the merge to save cost. **[Claude's call]**

### 6.3 Budget allocation ("cross-subsidy")
Input: **total budget** for all refills within the horizon (entered by the user).

1. Compute the unconstrained plan (all visits incl. extra visits, §6.2) at the chosen service level. Total need = `N`.
2. If budget ≥ N, fund everything and show the unused budget.
3. If budget < N, allocate **visit by visit in date order, re-projecting after each allocation** (an underfunded visit lowers the starting balance of the ATM's next visit, so that need is recomputed). **[Claude's call]**
   1. **Tier 1 (avoid cash-out)**: for each date, fund each visit up to its **p50 need**, i.e. the `need` formula with `q = p50`. `min` is already inside `need` and is counted once. Within the same date, the order is **earliest projected breach first**. Budget is reserved for future Tier 1 needs: before Tier 2 starts, run a full Tier 1 pass over the whole horizon.
   2. **Tier 2 (safety buffer)**: split the remainder across visits **in proportion to their p50→p_service gap**, then re-project.
   3. Over-stocked ATMs naturally get small amounts or skips. The amount freed compared with the current policy is shown as **"re-allocated"**, with arrows from the ATMs that gave cash to the ATMs that received it.
   4. Any visit still under its Tier 1 need is flagged **"Underfunded – cash-out likely on <date>"**.
4. Round every amount to `step` (down when budget-constrained) and respect `cap`.

### 6.4 Comparison with the current policy (headline numbers)
For the horizon, compare *Current policy* with *Recommended*:
- Projected cash-out days (p50)
- **Idle cash** = the average over all ATM-days in the horizon of `max(0, end-of-day balance − min_safe_balance)` (IDR), and its **opportunity cost** = idle cash × annual rate × days / 365. The rate is user-set, default 6%. **[Claude's call]**
- Number of visits (scheduled + extra) × `cost_per_visit`
- Total cash loaded

In **time-travel mode** (as-of date in the past), the same numbers are also computed by **replaying each plan against the demand that actually happened**:
- **Dummy data**: use `atm_true_demand.csv`, the real demand including what was lost on cash-out days.
- **Client data** (no ground truth): use the logged withdrawal. On censored days (closing = 0), use the larger of the logged withdrawal and the engine's in-sample p50 fit. These figures are labelled "estimated" in the UI. **[Claude's call]**

### 6.5 Overrides
The user can change any visit's date or amount, or mark it as skipped. The projected balance and comparison update instantly (no re-fit needed). Overrides are labelled "manual". They can be exported as CSV (`tid, visit_date, amount, source`).

## 7. Web screens

A global header on every screen: **As-of date** picker (default = last date in data), **Horizon** (7–30 days, default 14), **Service level**, a **Data source** badge (Dummy / Uploaded file name), and a recompute spinner.

1. **Fleet Overview**
   - KPI tiles: ATMs at cash-out risk, over-stocked ATMs, total idle cash, total recommended refill.
   - A table/cards with one row per TID: location, type, current balance, a gauge (balance vs capacity), days of cash left, next visit, status badge, and recommended amount.
   - A small map is optional and not required.
2. **ATM Detail (per TID)**
   - Main chart: actual withdrawal history (the last 90 days by default, zoomable to all) + forecast p50 with a p10–p90 band. Holidays are shaded, with Lebaran labelled.
   - Balance chart: actual balance (replenishment jumps marked), projected balance under the current policy vs the recommended plan, and a `min` line.
   - The recommendation card ("Refill Rp 640.000.000 on 12 Mar — projected to drop below safe minimum on 13 Mar due to pre-Lebaran demand +120%"), plus model name and backtest accuracy.
   - In time-travel mode, actuals after the as-of date are drawn as a dashed overlay.
3. **Allocation Planner**
   - Budget input, with the total need, funded %, and underfunded count.
   - Table: TID × visit date × recommended amount × allocated amount × override. Inline edits are allowed.
   - A flow visual showing **re-allocated cash** from over-stocked ATMs to at-risk ATMs.
   - Comparison panel (§6.4) and an Export CSV button.
4. **Data Editor**
   - Tabs: Daily Log, ATM Master, Holidays.
   - Upload CSV/XLSX, which replaces or merges data by (`tid`, `date`). There is a paginated, filterable table (by TID and date range) with inline editing, add row, and delete row.
   - Validation panel (§4.1). **Reset to dummy data** and **Download current data** buttons.
5. **Forecast Accuracy**
   - Per-TID table: chosen model, WAPE, MAPE, MAE, interval coverage, and Lebaran-check error. Each candidate model is shown next to the baseline.
   - Backtest chart: forecast vs actual for the selected origin(s).

Formatting: IDR with thousand separators (`Rp 640.000.000`), plus compact `Rp 640 jt` on tiles. Dates are shown as `12 Mar 2026`.

## 8. Non-functional requirements

- **Stack** **[Claude's call]**: backend **FastAPI** (Python 3.11+) with the forecast engine as a separate importable package (`engine/`). Frontend **React + Vite + TypeScript** with **ECharts** (good time-series zoom and bands) and a data-grid component for the editor.
- **Run locally**: one command (e.g. `run.ps1` / `make dev`) starts both. No internet is needed at presentation time; all assets are bundled.
- **Storage**: the current working dataset is saved to local files (CSV/Parquet or SQLite) so it survives restarts. The dummy data stays read-only and can always be restored.
- **Performance** on a normal laptop with 10 TIDs × 2 years:
  - First full fit + backtest: ≤ 60 s, with a progress indicator.
  - Recompute after a single-row edit (one TID re-fit): ≤ 5 s.
  - Override / budget change (no re-fit): ≤ 300 ms.
  - Should scale to ~100 TIDs (fits run in parallel across processes).
- **Determinism**: the same data and settings produce the same numbers.
- **Explainability**: every recommendation states the forecast, the rule, and the constraint behind it.

## 9. Acceptance criteria

1. Running `python data/generate_dummy.py` reproduces the shipped CSVs (log, master, holidays, true demand) byte-for-byte. The balance identity holds on all rows.
2. On a fresh start, all 5 screens work on the dummy data, with no errors in the console or API.
3. At least **7 of 10** TIDs pick a model that beats seasonal-naive on WAPE. The fleet-level WAPE at H = 14 is shown on the Accuracy page.
4. With as-of date 2026-03-01 and H = 21, the terminal and airport forecasts show the pre-Lebaran surge, and the p10–p90 band contains the actual peak day.
5. Editing one withdrawal value (e.g. ×3 on the last day) visibly changes that TID's forecast/recommendation within 5 s. Other TIDs are unchanged.
6. Uploading a CSV with the §4.1 columns replaces the data. A file with broken rows shows the validation messages and does not crash.
7. With a budget equal to 70% of total need, the Tier 1 needs of the most urgent ATMs are funded first. No allocation exceeds capacity, and all amounts are multiples of the denomination.
8. For the dummy data in time-travel mode (as-of 2026-03-01, H = 30, budget unconstrained), replaying against `atm_true_demand.csv` gives **fewer cash-out days** fleet-wide than the current policy. It also gives **less idle cash** at hospital, campus, and residential. The extra-visit cost is shown next to it.
9. On the default **Pre-Lebaran 2026** scenario, the Fleet Overview shows at least one *Cash-out risk* ATM and at least one *Over-stocked* ATM. With a budget at 70% of need, the Planner shows cash re-allocated from over-stocked to at-risk ATMs.
10. Uploading a log with unknown TIDs creates inferred master rows flagged for review, and the forecast runs on them.

## 10. Open items for the builder

- Choose the exact SARIMAX order grid and Holt-Winters variants (keep the fit time within §8).
- Choose the data-grid library (e.g. AG Grid Community or TanStack Table).
- Decide how to draw the "re-allocated cash" visual (a Sankey diagram or simple arrows).
- Verify the 2026 Islamic holiday dates against the official SKB before showing the demo to the client.
- Real client logs may contain several log rows per day or intraday timestamps. Add a daily-aggregation step if needed (the dummy data is already daily).
