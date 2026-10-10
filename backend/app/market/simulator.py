"""GBM market simulator and its asyncio data source wrapper."""

from __future__ import annotations

import asyncio
import logging
import math
import random

import numpy as np

from .cache import PriceCache
from .interface import MarketDataSource
from .seed_prices import (
    CROSS_GROUP_CORR,
    DEFAULT_PARAMS,
    FINANCE_TICKERS,
    INTRA_FINANCE_CORR,
    INTRA_TECH_CORR,
    SEED_PRICES,
    TECH_TICKERS,
    TICKER_PARAMS,
    TSLA_CORR,
)

logger = logging.getLogger(__name__)


def _norm(ticker: str) -> str:
    return ticker.strip().upper()


def _pairwise_correlation(a: str, b: str) -> float:
    if a == "TSLA" or b == "TSLA":
        return TSLA_CORR
    if a in TECH_TICKERS and b in TECH_TICKERS:
        return INTRA_TECH_CORR
    if a in FINANCE_TICKERS and b in FINANCE_TICKERS:
        return INTRA_FINANCE_CORR
    return CROSS_GROUP_CORR


class GBMSimulator:
    # 500ms as a fraction of a trading year (252 days * 6.5h)
    DEFAULT_DT = 0.5 / (252 * 6.5 * 3600)

    def __init__(
        self,
        tickers: list[str],
        dt: float = DEFAULT_DT,
        event_probability: float = 0.001,
    ) -> None:
        self._dt = dt
        self._event_probability = event_probability
        self._tickers: list[str] = []
        self._prices: dict[str, float] = {}
        self._params: dict[str, dict[str, float]] = {}
        self._cholesky: np.ndarray | None = None
        for t in tickers:
            self._register(_norm(t))
        self._rebuild_cholesky()

    def _register(self, ticker: str) -> None:
        if ticker in self._prices:
            return
        self._tickers.append(ticker)
        self._prices[ticker] = SEED_PRICES.get(ticker) or random.uniform(50, 300)
        self._params[ticker] = TICKER_PARAMS.get(ticker, DEFAULT_PARAMS)

    def _rebuild_cholesky(self) -> None:
        n = len(self._tickers)
        if n == 0:
            self._cholesky = None
            return
        corr = np.eye(n)
        for i in range(n):
            for j in range(i + 1, n):
                rho = _pairwise_correlation(self._tickers[i], self._tickers[j])
                corr[i, j] = corr[j, i] = rho
        self._cholesky = np.linalg.cholesky(corr)

    def step(self) -> dict[str, float]:
        """Advance every ticker one tick; returns prices rounded to cents."""
        if not self._tickers:
            return {}
        z = self._cholesky @ np.random.standard_normal(len(self._tickers))
        sqrt_dt = math.sqrt(self._dt)
        out: dict[str, float] = {}
        for i, t in enumerate(self._tickers):
            sigma = self._params[t]["sigma"]
            mu = self._params[t]["mu"]
            drift = (mu - 0.5 * sigma**2) * self._dt
            price = self._prices[t] * math.exp(drift + sigma * sqrt_dt * z[i])
            if random.random() < self._event_probability:
                shock = random.uniform(0.02, 0.05) * random.choice((-1, 1))
                price *= 1 + shock
            self._prices[t] = price
            out[t] = round(price, 2)
        return out

    def add_ticker(self, ticker: str) -> None:
        ticker = _norm(ticker)
        if ticker in self._prices:
            return
        self._register(ticker)
        self._rebuild_cholesky()

    def remove_ticker(self, ticker: str) -> None:
        ticker = _norm(ticker)
        if ticker not in self._prices:
            return
        self._tickers.remove(ticker)
        del self._prices[ticker]
        del self._params[ticker]
        self._rebuild_cholesky()

    def get_price(self, ticker: str) -> float | None:
        price = self._prices.get(_norm(ticker))
        return None if price is None else round(price, 2)

    def get_tickers(self) -> list[str]:
        return list(self._tickers)


class SimulatorDataSource(MarketDataSource):
    def __init__(
        self,
        cache: PriceCache,
        update_interval: float = 0.5,
        event_probability: float = 0.001,
    ) -> None:
        self._cache = cache
        self._interval = update_interval
        self._event_probability = event_probability
        self._sim: GBMSimulator | None = None
        self._task: asyncio.Task | None = None

    def _seed_cache(self, ticker: str) -> None:
        assert self._sim is not None
        price = self._sim.get_price(ticker)
        if price is not None:
            # Seed price is the day's reference for daily change %
            self._cache.update(ticker, price, reference_price=price)

    async def start(self, tickers: list[str]) -> None:
        if self._task is not None:
            return
        self._sim = GBMSimulator(tickers, event_probability=self._event_probability)
        for t in self._sim.get_tickers():
            self._seed_cache(t)
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def add_ticker(self, ticker: str) -> None:
        if self._sim is None:
            return
        ticker = _norm(ticker)
        if ticker in self._sim.get_tickers():
            return
        self._sim.add_ticker(ticker)
        self._seed_cache(ticker)

    async def remove_ticker(self, ticker: str) -> None:
        ticker = _norm(ticker)
        if self._sim is not None:
            self._sim.remove_ticker(ticker)
        self._cache.remove(ticker)

    def get_tickers(self) -> list[str]:
        return self._sim.get_tickers() if self._sim else []

    async def _run_loop(self) -> None:
        while True:
            try:
                assert self._sim is not None
                for ticker, price in self._sim.step().items():
                    self._cache.update(ticker, price)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Simulator step failed")
            await asyncio.sleep(self._interval)
