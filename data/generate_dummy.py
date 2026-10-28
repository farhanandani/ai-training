"""Generate dummy daily ATM balance logs for the Cash Forecasting demo.

Pure standard library (no numpy/pandas) so it runs anywhere. Seeded, so every
run produces identical files.

Outputs (written next to this script):
    atm_true_demand.csv  dummy-only ground truth (demand before cash-out capping)
    holidays_id.csv    Indonesian holiday calendar used by the generator and engine
    atm_master.csv     one row per ATM (TID) with its constraints
    atm_daily_log.csv  one row per TID per day

Simulation model per ATM per day:
    demand      = base * day_of_week * payday * holiday/season * trend * noise
    replenish   = happens in the morning, before withdrawals
                  - scheduled: every `replenish_cycle_days`, topped up to a fixed
                    target level (the client's current "static" policy)
                  - emergency: sometimes the day after the ATM ran nearly empty
    withdrawal  = min(demand, opening + replenishment)   -> stock-out when capped
    closing     = opening - withdrawal + replenishment
"""

import csv
import random
from datetime import date, timedelta
from pathlib import Path

SEED = 20261028
START = date(2024, 10, 28)
END = date(2026, 10, 27)
OUT_DIR = Path(__file__).resolve().parent

# --------------------------------------------------------------------------
# Holiday calendar (Indonesia). Dates follow the government SKB where known;
# 2026 Islamic dates are approximate and should be checked before real use.
# type: new_year | christmas | idul_fitri | cuti_bersama | national
# --------------------------------------------------------------------------
HOLIDAYS = [
    ("2024-12-25", "Christmas Day", "christmas"),
    ("2024-12-26", "Christmas Collective Leave", "cuti_bersama"),
    ("2025-01-01", "New Year's Day", "new_year"),
    ("2025-01-27", "Isra Mi'raj", "national"),
    ("2025-01-29", "Chinese New Year", "national"),
    ("2025-03-29", "Nyepi", "national"),
    ("2025-03-28", "Nyepi Collective Leave", "cuti_bersama"),
    ("2025-03-31", "Idul Fitri 1446 H (day 1)", "idul_fitri"),
    ("2025-04-01", "Idul Fitri 1446 H (day 2)", "idul_fitri"),
    ("2025-04-02", "Idul Fitri Collective Leave", "cuti_bersama"),
    ("2025-04-03", "Idul Fitri Collective Leave", "cuti_bersama"),
    ("2025-04-04", "Idul Fitri Collective Leave", "cuti_bersama"),
    ("2025-04-07", "Idul Fitri Collective Leave", "cuti_bersama"),
    ("2025-04-18", "Good Friday", "national"),
    ("2025-05-01", "Labour Day", "national"),
    ("2025-05-12", "Vesak Day", "national"),
    ("2025-05-29", "Ascension of Jesus", "national"),
    ("2025-06-01", "Pancasila Day", "national"),
    ("2025-06-06", "Idul Adha 1446 H", "national"),
    ("2025-06-27", "Islamic New Year 1447 H", "national"),
    ("2025-08-17", "Independence Day", "national"),
    ("2025-09-05", "Prophet's Birthday", "national"),
    ("2025-12-25", "Christmas Day", "christmas"),
    ("2025-12-26", "Christmas Collective Leave", "cuti_bersama"),
    ("2026-01-01", "New Year's Day", "new_year"),
    ("2026-01-16", "Isra Mi'raj", "national"),
    ("2026-02-17", "Chinese New Year", "national"),
    ("2026-03-19", "Nyepi", "national"),
    ("2026-03-18", "Nyepi Collective Leave", "cuti_bersama"),
    ("2026-03-20", "Idul Fitri 1447 H (day 1)", "idul_fitri"),
    ("2026-03-21", "Idul Fitri 1447 H (day 2)", "idul_fitri"),
    ("2026-03-23", "Idul Fitri Collective Leave", "cuti_bersama"),
    ("2026-03-24", "Idul Fitri Collective Leave", "cuti_bersama"),
    ("2026-04-03", "Good Friday", "national"),
    ("2026-05-01", "Labour Day", "national"),
    ("2026-05-14", "Ascension of Jesus", "national"),
    ("2026-05-27", "Idul Adha 1447 H", "national"),
    ("2026-05-31", "Vesak Day", "national"),
    ("2026-06-01", "Pancasila Day", "national"),
    ("2026-06-16", "Islamic New Year 1448 H", "national"),
    ("2026-08-17", "Independence Day", "national"),
    ("2026-08-25", "Prophet's Birthday", "national"),
    # Future dates inside a typical forecast horizon
    ("2026-12-25", "Christmas Day", "christmas"),
    ("2026-12-26", "Christmas Collective Leave", "cuti_bersama"),
    ("2027-01-01", "New Year's Day", "new_year"),
]

# --------------------------------------------------------------------------
# ATM fleet. Amounts in IDR.
#   base          average daily demand on a normal weekday
#   target        level the static policy tops up to on each scheduled visit
# --------------------------------------------------------------------------
M = 1_000_000
ATMS = [
    # tid, name, type, capacity, min_safe, cycle, denom, cost, base, target
    # ("TID-JKT-0001", "Grand Indonesia Mall", "mall", 1_000 * M, 120 * M, 4, 100_000, 1_500_000, 165 * M, 720 * M),
    ("TID-JKT-0001", "Grand Indonesia Mall", "mall", 1_000 * M, 120 * M, 4, 100_000, 1_500_000, 165 * M, 900 * M),
    # ("TID-JKT-0002", "Sudirman Office Tower", "office", 800 * M, 100 * M, 5, 100_000, 1_500_000, 115 * M, 640 * M),
    ("TID-JKT-0002", "Sudirman Office Tower", "office", 800 * M, 100 * M, 5, 100_000, 1_500_000, 115 * M, 700 * M),
    # ("TID-JKT-0003", "Pasar Tanah Abang", "traditional_market", 900 * M, 110 * M, 3, 50_000, 1_250_000, 150 * M, 560 * M),
    ("TID-JKT-0003", "Pasar Tanah Abang", "traditional_market", 900 * M, 110 * M, 3, 50_000, 1_250_000, 150 * M, 720 * M),
    # ("TID-DPK-0004", "Universitas Indonesia Campus", "campus", 500 * M, 50 * M, 7, 50_000, 1_750_000, 48 * M, 450 * M),
    ("TID-DPK-0004", "Universitas Indonesia Campus", "campus", 600 * M, 50 * M, 7, 50_000, 1_750_000, 48 * M, 600 * M),
    # ("TID-BKS-0005", "Harapan Indah Residence", "residential", 600 * M, 60 * M, 7, 100_000, 1_750_000, 55 * M, 600 * M),
    ("TID-BKS-0005", "Harapan Indah Residence", "residential", 800 * M, 60 * M, 7, 100_000, 1_750_000, 55 * M, 800 * M),
    # ("TID-TNG-0006", "Soekarno-Hatta Airport T3", "airport", 1_200 * M, 150 * M, 3, 100_000, 2_000_000, 210 * M, 760 * M),
    ("TID-TNG-0006", "Soekarno-Hatta Airport T3", "airport", 1_200 * M, 150 * M, 3, 100_000, 2_000_000, 210 * M, 950 * M),
    # ("TID-JKT-0007", "Terminal Pulo Gebang", "bus_terminal", 900 * M, 110 * M, 4, 50_000, 1_500_000, 140 * M, 620 * M),
    ("TID-JKT-0007", "Terminal Pulo Gebang", "bus_terminal", 900 * M, 110 * M, 4, 50_000, 1_500_000, 140 * M, 820 * M),
    # ("TID-JKT-0008", "RS Cipto Mangunkusumo", "hospital", 500 * M, 50 * M, 7, 100_000, 1_500_000, 40 * M, 500 * M),
    ("TID-JKT-0008", "RS Cipto Mangunkusumo", "hospital", 600 * M, 50 * M, 7, 100_000, 1_500_000, 40 * M, 600 * M),
    # ("TID-BKS-0009", "Jababeka Industrial Estate", "industrial", 800 * M, 90 * M, 5, 100_000, 2_000_000, 105 * M, 560 * M),
    ("TID-BKS-0009", "Jababeka Industrial Estate", "industrial", 800 * M, 90 * M, 5, 100_000, 2_000_000, 105 * M, 680 * M),
    # ("TID-BAL-0010", "Kuta Beach Walk", "tourist", 900 * M, 100 * M, 4, 100_000, 2_250_000, 125 * M, 600 * M),
    ("TID-BAL-0010", "Kuta Beach Walk", "tourist", 900 * M, 100 * M, 4, 100_000, 2_250_000, 125 * M, 780 * M),
]

# Monday..Sunday multipliers
DOW = {
    "mall": [0.85, 0.85, 0.90, 0.95, 1.15, 1.40, 1.30],
    "office": [1.10, 1.05, 1.05, 1.05, 1.20, 0.50, 0.40],
    "traditional_market": [1.00, 1.00, 1.00, 1.00, 1.05, 1.15, 1.10],
    "campus": [1.10, 1.05, 1.05, 1.05, 1.10, 0.70, 0.60],
    "residential": [0.95, 0.95, 0.95, 1.00, 1.10, 1.15, 1.10],
    "airport": [1.00, 0.90, 0.90, 1.00, 1.20, 1.10, 1.15],
    "bus_terminal": [1.00, 0.90, 0.90, 1.00, 1.20, 1.15, 1.10],
    "hospital": [1.05, 1.05, 1.00, 1.00, 1.00, 0.95, 0.90],
    "industrial": [1.05, 1.00, 1.00, 1.00, 1.10, 0.90, 0.60],
    "tourist": [0.80, 0.80, 0.85, 0.90, 1.15, 1.45, 1.35],
}

# Types where workplaces close on holidays -> demand drops
CLOSES_ON_HOLIDAY = {"office", "industrial", "campus"}
# Peak multiplier on the last day before Idul Fitri (mudik / THR spending)
LEBARAN_PEAK = {
    "mall": 2.2, "office": 1.6, "traditional_market": 2.4, "campus": 1.3,
    "residential": 2.0, "airport": 3.0, "bus_terminal": 3.2, "hospital": 1.4,
    "industrial": 1.8, "tourist": 1.7,
}
# Multiplier during Idul Fitri days + collective leave
LEBARAN_HOLIDAY = {
    "mall": 1.4, "office": 0.3, "traditional_market": 0.6, "campus": 0.3,
    "residential": 0.8, "airport": 1.5, "bus_terminal": 1.6, "hospital": 0.9,
    "industrial": 0.3, "tourist": 1.6,
}
# Year-end (Christmas -> New Year) uplift
YEAR_END = {
    "mall": 1.6, "office": 1.1, "traditional_market": 1.3, "campus": 0.8,
    "residential": 1.2, "airport": 1.5, "bus_terminal": 1.4, "hospital": 1.0,
    "industrial": 1.1, "tourist": 1.9,
}
PAYDAY_STRONG = {"office", "industrial", "residential", "traditional_market"}


def load_holidays():
    by_date = {}
    for d, name, kind in HOLIDAYS:
        by_date[date.fromisoformat(d)] = (name, kind)
    return by_date


def season_multiplier(day, atm_type, holidays, fitri_days):
    """Combined holiday / Ramadan / year-end effect for one day."""
    m = 1.0

    # Idul Fitri: Ramadan uplift, THR build-up, peak just before, drop/shift during
    for fitri in fitri_days:
        d = (fitri - day).days  # days until Idul Fitri day 1
        if 11 <= d <= 30:  # Ramadan, THR paid ~2 weeks before
            m *= 1.10 if d > 20 else 1.20
        elif 1 <= d <= 10:  # linear ramp to the peak on the last day
            peak = LEBARAN_PEAK[atm_type]
            m *= 1.3 + (peak - 1.3) * (10 - d) / 9
        elif -6 <= d <= 0:  # holiday + collective leave week
            m *= LEBARAN_HOLIDAY[atm_type]
        elif -13 <= d <= -7:  # arus balik, back-to-work spending
            m *= 1.15 if atm_type in ("airport", "bus_terminal") else 1.0

    # Year-end: Dec 20 - Dec 31 uplift, Jan 1 quiet for workplaces
    if day.month == 12 and day.day >= 20:
        m *= YEAR_END[atm_type]
    if day.month == 1 and day.day == 1:
        m *= 0.5 if atm_type in CLOSES_ON_HOLIDAY else 0.9

    # Other holidays: small pre-holiday uplift, drop on the day for workplaces
    hol = holidays.get(day)
    if hol and hol[1] in ("national", "cuti_bersama", "christmas"):
        if not any(-6 <= (f - day).days <= 0 for f in fitri_days):
            m *= 0.4 if atm_type in CLOSES_ON_HOLIDAY else 1.05
    nxt = holidays.get(day + timedelta(days=1))
    if nxt and nxt[1] == "national":
        m *= 1.20
    return m


def payday_multiplier(day, atm_type):
    if day.day >= 25 or day.day <= 3:
        return 1.25 if atm_type in PAYDAY_STRONG else 1.10
    return 1.0


def round_down(value, step):
    return int(value // step) * step


def simulate_atm(atm, holidays, fitri_days, rng):
    tid, _name, atm_type, capacity, _min_safe, cycle, denom, _cost, base, target = atm
    rows = []
    balance = target
    days_total = (END - START).days + 1
    # Stagger the first scheduled visit so ATMs are not all refilled on the same day
    offset = rng.randrange(cycle)
    emergency_pending = False

    for i in range(days_total):
        day = START + timedelta(days=i)
        opening = balance

        # --- replenishment (morning) ---
        replenishment = 0
        scheduled = (i - offset) % cycle == 0
        if scheduled or emergency_pending:
            top_up = round_down(min(target, capacity) - opening, denom)
            if top_up > 0:
                replenishment = top_up
            emergency_pending = False

        # --- demand ---
        trend = 1.0 + 0.06 * i / 365  # ~6% yearly growth
        noise = rng.lognormvariate(0, 0.12)
        if rng.random() < 0.01:  # rare unexplained spike
            noise *= rng.uniform(1.5, 2.2)
        demand = (base * DOW[atm_type][day.weekday()] * payday_multiplier(day, atm_type)
                  * season_multiplier(day, atm_type, holidays, fitri_days) * trend * noise)
        # ATM out of service a handful of days per year
        if rng.random() < 0.004:
            demand = 0

        available = opening + replenishment
        # withdrawal = min(round_down(demand, 50_000), available)
        true_demand = round_down(demand, 50_000)
        withdrawal = min(true_demand, available)
        closing = available - withdrawal

        # Ran (nearly) empty -> ops sometimes sends an emergency visit next day
        if closing < 0.05 * capacity and rng.random() < 0.6:
            emergency_pending = True

        rows.append({
            "tid": tid,
            "date": day.isoformat(),
            "opening_balance": opening,
            "withdrawal": withdrawal,
            "replenishment": replenishment,
            "closing_balance": closing,
            # Not part of the log: ground truth, written to a separate file
            "true_demand": true_demand,
        })
        balance = closing
    return rows


def main():
    rng = random.Random(SEED)
    holidays = load_holidays()
    # Day 1 of each Idul Fitri = an idul_fitri date whose previous day is not idul_fitri
    fitri_days = sorted({d for d, (_, kind) in holidays.items() if kind == "idul_fitri"
                         and holidays.get(d - timedelta(days=1), ("", ""))[1] != "idul_fitri"})

    with open(OUT_DIR / "holidays_id.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["date", "name", "type"])
        for d in sorted(holidays):
            w.writerow([d.isoformat(), *holidays[d]])

    with open(OUT_DIR / "atm_master.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        # w.writerow(["tid", "location_name", "location_type", "capacity", "min_safe_balance",
        #             "replenish_cycle_days", "denomination", "cost_per_visit"])
        w.writerow(["tid", "location_name", "location_type", "capacity", "min_safe_balance",
                    "replenish_cycle_days", "denomination", "cost_per_visit", "current_fill_level"])
        for atm in ATMS:
            # w.writerow(atm[:8])
            # current_fill_level = the static target the client tops up to today (baseline policy)
            w.writerow([*atm[:8], atm[9]])

    all_rows = []
    for atm in ATMS:
        all_rows.extend(simulate_atm(atm, holidays, fitri_days, rng))

    log_fields = ["tid", "date", "opening_balance", "withdrawal", "replenishment", "closing_balance"]
    with open(OUT_DIR / "atm_daily_log.csv", "w", newline="", encoding="utf-8") as f:
        # w = csv.DictWriter(f, fieldnames=list(all_rows[0].keys()))
        w = csv.DictWriter(f, fieldnames=log_fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(all_rows)

    # Dummy-only ground truth: real demand before it was capped by an empty ATM.
    # Real client logs never have this; the engine must not read it for fitting.
    with open(OUT_DIR / "atm_true_demand.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["tid", "date", "true_demand"], extrasaction="ignore")
        w.writeheader()
        w.writerows(all_rows)

    print(f"Wrote {len(ATMS)} ATMs, {len(all_rows)} daily rows, {len(holidays)} holidays to {OUT_DIR}")


if __name__ == "__main__":
    main()
