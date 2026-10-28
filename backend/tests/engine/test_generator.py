import csv
import hashlib
import shutil
import subprocess
import sys


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_generator_reproducible_and_balanced(tmp_path, seed_dir):
    shutil.copy(seed_dir / "generate_dummy.py", tmp_path / "generate_dummy.py")
    subprocess.run([sys.executable, "-I", str(tmp_path / "generate_dummy.py")], check=True, cwd=tmp_path)
    for name in ["atm_daily_log.csv", "atm_master.csv", "holidays_id.csv", "atm_true_demand.csv"]:
        assert sha256(tmp_path / name) == sha256(seed_dir / name)
    with open(tmp_path / "atm_daily_log.csv", newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 7300
    assert all(
        int(r["opening_balance"]) - int(r["withdrawal"]) + int(r["replenishment"])
        == int(r["closing_balance"])
        for r in rows
    )
