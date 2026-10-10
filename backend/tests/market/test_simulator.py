import asyncio
import random

import numpy as np
import pytest

from app.market.cache import PriceCache
from app.market.seed_prices import SEED_PRICES
from app.market.simulator import (
    GBMSimulator,
    SimulatorDataSource,
    _pairwise_correlation,
)

DEFAULTS = list(SEED_PRICES)


def test_step_returns_all_tickers_positive():
    sim = GBMSimulator(DEFAULTS)
    out = sim.step()
    assert set(out) == set(DEFAULTS)
    assert all(p > 0 for p in out.values())


def test_prices_stay_positive_long_run():
    sim = GBMSimulator(DEFAULTS, event_probability=0.01)
    for _ in range(20000):
        out = sim.step()
    assert all(p > 0 for p in out.values())


def test_reproducible_with_seed():
    def run():
        random.seed(1)
        np.random.seed(1)
        s = GBMSimulator(["AAPL", "MSFT"])
        return [s.step() for _ in range(10)]

    assert run() == run()


def test_events_probability_extremes():
    # sigma tiny dt => without events price barely moves
    never = GBMSimulator(["AAPL"], event_probability=0.0)
    for _ in range(200):
        never.step()
    assert abs(never.get_price("AAPL") - 190.0) < 5

    always = GBMSimulator(["AAPL"], event_probability=1.0)
    prev = 190.0
    for _ in range(20):
        cur = always.step()["AAPL"]
        assert abs(cur / prev - 1) >= 0.019
        prev = cur


def test_correlation_matrix_values():
    assert _pairwise_correlation("AAPL", "MSFT") == 0.6
    assert _pairwise_correlation("JPM", "V") == 0.5
    assert _pairwise_correlation("TSLA", "AAPL") == 0.3
    assert _pairwise_correlation("AAPL", "JPM") == 0.3
    assert _pairwise_correlation("XYZ", "ABC") == 0.3


def test_sample_correlation():
    np.random.seed(0)
    random.seed(0)
    sim = GBMSimulator(["AAPL", "MSFT", "TSLA"], dt=1e-4, event_probability=0.0)
    rets = {t: [] for t in ["AAPL", "MSFT", "TSLA"]}
    last = {t: sim._prices[t] for t in rets}
    for _ in range(5000):
        sim.step()
        for t in rets:
            rets[t].append(np.log(sim._prices[t] / last[t]))
            last[t] = sim._prices[t]
    tech = np.corrcoef(rets["AAPL"], rets["MSFT"])[0, 1]
    tsla = np.corrcoef(rets["AAPL"], rets["TSLA"])[0, 1]
    assert abs(tech - 0.6) < 0.08
    assert tsla < tech


def test_add_remove_tickers():
    sim = GBMSimulator(["AAPL"])
    sim.add_ticker("pypl")
    assert sim.get_tickers() == ["AAPL", "PYPL"]
    assert 50 <= sim.get_price("PYPL") <= 300
    assert sim._cholesky.shape == (2, 2)
    sim.add_ticker("PYPL")  # duplicate no-op
    assert len(sim.get_tickers()) == 2
    sim.remove_ticker("AAPL")
    sim.remove_ticker("NOPE")
    assert sim.get_tickers() == ["PYPL"]
    assert sim._cholesky.shape == (1, 1)
    sim.remove_ticker("PYPL")
    assert sim.step() == {}
    assert sim.get_price("PYPL") is None


def test_seed_prices_used():
    sim = GBMSimulator(["NVDA"])
    assert sim.get_price("NVDA") == 800.0


async def test_source_start_populates_cache_and_stop_idempotent():
    cache = PriceCache()
    src = SimulatorDataSource(cache, update_interval=0.01)
    await src.start(DEFAULTS)
    assert set(cache.get_all()) == set(DEFAULTS)
    assert cache.get("AAPL").reference_price == 190.0
    v = cache.version
    await asyncio.sleep(0.1)
    assert cache.version > v
    await src.stop()
    await src.stop()


async def test_source_add_remove():
    cache = PriceCache()
    src = SimulatorDataSource(cache, update_interval=0.01)
    await src.add_ticker("AAPL")  # before start: ignored
    assert cache.get("AAPL") is None
    await src.start(["AAPL"])
    await src.add_ticker("pypl")
    assert cache.get_price("PYPL") is not None
    assert "PYPL" in src.get_tickers()
    await src.remove_ticker("PYPL")
    assert cache.get("PYPL") is None
    assert src.get_tickers() == ["AAPL"]
    await src.stop()


async def test_source_survives_step_failure(monkeypatch):
    cache = PriceCache()
    src = SimulatorDataSource(cache, update_interval=0.01)
    await src.start(["AAPL"])
    calls = {"n": 0}
    real = src._sim.step

    def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return real()

    monkeypatch.setattr(src._sim, "step", flaky)
    await asyncio.sleep(0.1)
    assert calls["n"] > 1
    await src.stop()


async def test_start_twice_is_noop():
    src = SimulatorDataSource(PriceCache(), update_interval=0.01)
    await src.start(["AAPL"])
    task = src._task
    await src.start(["AAPL"])
    assert src._task is task
    await src.stop()
    assert src.get_tickers() == ["AAPL"]
