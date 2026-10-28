import numpy as np

from engine.plan import simulate_balance


def test_simulate_identity_property():
    rng = np.random.default_rng(1)
    for _ in range(200):
        h = int(rng.integers(1, 31))
        cap = int(rng.integers(1, 10)) * 100_000_000
        b0 = int(rng.integers(0, cap + 1))
        demand = rng.uniform(0, 3e8, h)
        loads = np.where(rng.random(h) < 0.2, rng.integers(0, cap + 1, h), 0).astype(np.int64)
        r = simulate_balance(b0, demand, loads, cap)
        assert np.array_equal(r.closing, r.opening - r.withdrawal + r.loads)
        assert np.all(r.withdrawal <= r.opening + r.loads)
        assert np.all(r.opening >= 0) and np.all(r.withdrawal >= 0) and np.all(r.closing >= 0)
        assert np.all(r.loads >= 0) and np.all(r.opening + r.loads <= max(cap, b0))
        assert r.opening[0] == b0
        assert np.array_equal(r.opening[1:], r.closing[:-1])


def test_cash_out_flag():
    r = simulate_balance(100, np.array([60.0, 60.0]), np.array([0, 0]), 1000)
    assert r.withdrawal.tolist() == [60, 40]
    assert r.cash_out.tolist() == [False, True]


def test_load_clamped_to_capacity():
    r = simulate_balance(900, np.array([0.0]), np.array([500]), 1000)
    assert r.loads.tolist() == [100]
    assert r.closing.tolist() == [1000]
