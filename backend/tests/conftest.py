from pathlib import Path

import pandas as pd
import pytest

from engine.ingest import read_table
from engine.schema import AtmMaster


@pytest.fixture
def seed_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "data"


_SEED = Path(__file__).resolve().parents[2] / "data"


def _load(name: str, kind: str) -> pd.DataFrame:
    return read_table((_SEED / name).read_bytes(), name, kind)[0]


@pytest.fixture(scope="session")
def log_df() -> pd.DataFrame:
    return _load("atm_daily_log.csv", "log")


@pytest.fixture(scope="session")
def master_list() -> list[AtmMaster]:
    df = _load("atm_master.csv", "master")
    rows = []
    for r in df.to_dict("records"):
        nv = r.get("next_visit_date")
        r["next_visit_date"] = None if nv is None or pd.isna(nv) else nv
        rows.append(AtmMaster(**{k: r[k] for k in AtmMaster.__dataclass_fields__ if k in r}))
    return rows


@pytest.fixture(scope="session")
def holidays_df() -> pd.DataFrame:
    return _load("holidays_id.csv", "holidays")


@pytest.fixture
def store(tmp_path, seed_dir):
    from app.store import Store

    s = Store(tmp_path / "workspace.db", seed_dir)
    yield s
    s.close()
