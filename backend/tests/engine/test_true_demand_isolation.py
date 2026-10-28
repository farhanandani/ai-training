"""TR-16: forecasting code never touches the dummy ground truth `true_demand`."""

import inspect
from pathlib import Path

import engine
from engine.forecast import run_tid

ENGINE = Path(engine.__file__).resolve().parent
FORECASTING = [
    ENGINE / "forecast.py",
    ENGINE / "backtest.py",
    ENGINE / "preprocess.py",
    ENGINE / "calendar.py",
    *sorted((ENGINE / "models").glob("*.py")),
]


def test_true_demand_isolation():
    assert len(FORECASTING) > 4  # models/* found
    for path in FORECASTING:
        assert "true_demand" not in path.read_text(encoding="utf-8"), path.name
    assert "true_demand" not in inspect.signature(run_tid).parameters
