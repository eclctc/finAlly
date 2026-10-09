"""Massive (Polygon.io) REST polling data source."""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import time

from .cache import PriceCache
from .interface import MarketDataSource

logger = logging.getLogger(__name__)


def _norm(ticker: str) -> str:
    return ticker.strip().upper()


def _get(obj, name):
    return getattr(obj, name, None) if obj is not None else None


def _snapshot_price(snap) -> float | None:
    """lastTrade -> min bar -> day bar -> prev day close."""
    candidates = (
        _get(_get(snap, "last_trade"), "price"),
        _get(_get(snap, "min"), "close"),
        _get(_get(snap, "day"), "close"),
        _get(_get(snap, "prev_day"), "close"),
    )
    for c in candidates:
        if c:
            return float(c)
    return None


def _snapshot_timestamp(snap) -> float:
    """Normalize to Unix seconds (min.t / updated are ms or ns)."""
    raw = _get(_get(snap, "min"), "timestamp") or _get(snap, "updated")
    if not raw:
        return time.time()
    raw = float(raw)
    if raw > 1e17:  # nanoseconds
        return raw / 1e9
    if raw > 1e11:  # milliseconds
        return raw / 1e3
    return raw


class MassiveDataSource(MarketDataSource):
    def __init__(
        self,
        cache: PriceCache,
        api_key: str,
        poll_interval: float = 15.0,
        client=None,
    ) -> None:
        self._cache = cache
        self._api_key = api_key
        self._interval = poll_interval
        self._client = client
        self._tickers: list[str] = []
        self._task: asyncio.Task | None = None
        self._snapshot_forbidden = False

    def _get_client(self):
        if self._client is None:
            from massive import RESTClient

            self._client = RESTClient(api_key=self._api_key)
        return self._client

    async def start(self, tickers: list[str]) -> None:
        if self._task is not None:
            return
        self._tickers = list(dict.fromkeys(_norm(t) for t in tickers))
        await self._poll_once()
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
        ticker = _norm(ticker)
        if ticker not in self._tickers:
            self._tickers.append(ticker)

    async def remove_ticker(self, ticker: str) -> None:
        ticker = _norm(ticker)
        if ticker in self._tickers:
            self._tickers.remove(ticker)
        self._cache.remove(ticker)

    def get_tickers(self) -> list[str]:
        return list(self._tickers)

    async def _run_loop(self) -> None:
        while True:
            await asyncio.sleep(self._interval)
            await self._poll_once()

    async def _poll_once(self) -> None:
        if not self._tickers:
            return
        try:
            await asyncio.to_thread(self._fetch, list(self._tickers))
        except Exception:
            logger.exception("Massive poll failed")

    def _fetch(self, tickers: list[str]) -> None:
        """Blocking; runs in a worker thread."""
        if not self._snapshot_forbidden:
            try:
                self._fetch_snapshot(tickers)
                return
            except Exception as exc:
                if getattr(exc, "status", None) == 403 or "403" in str(exc):
                    logger.warning(
                        "Massive snapshot not available on this plan (403); "
                        "falling back to end-of-day grouped bars"
                    )
                    self._snapshot_forbidden = True
                else:
                    raise
        self._fetch_grouped_daily(tickers)

    def _fetch_snapshot(self, tickers: list[str]) -> None:
        snaps = self._get_client().get_snapshot_all("stocks", tickers=tickers)
        for snap in snaps:
            ticker = _norm(getattr(snap, "ticker", "") or "")
            price = _snapshot_price(snap)
            if not ticker or price is None or ticker not in self._tickers:
                continue
            ref = _get(_get(snap, "prev_day"), "close") or None
            self._cache.update(
                ticker, price, _snapshot_timestamp(snap), reference_price=ref
            )

    def _fetch_grouped_daily(self, tickers: list[str]) -> None:
        wanted = set(tickers)
        day = dt.date.today() - dt.timedelta(days=1)
        for _ in range(7):  # step back over weekends/holidays
            bars = self._get_client().get_grouped_daily_aggs(
                day.isoformat(), adjusted=True
            )
            closes = {
                _norm(b.ticker): b.close
                for b in bars or []
                if _norm(b.ticker) in wanted and b.close
            }
            if closes:
                now = time.time()
                for t, close in closes.items():
                    self._cache.update(
                        t, float(close), now, reference_price=float(close)
                    )
                return
            day -= dt.timedelta(days=1)
        logger.warning("No grouped daily bars found in the last 7 days")
