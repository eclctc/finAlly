"""Thread-safe in-memory price cache."""

from __future__ import annotations

import threading
import time

from .models import PriceUpdate


class PriceCache:
    def __init__(self) -> None:
        self._data: dict[str, PriceUpdate] = {}
        self._lock = threading.Lock()
        self._version = 0

    def update(
        self,
        ticker: str,
        price: float,
        timestamp: float | None = None,
        reference_price: float | None = None,
    ) -> PriceUpdate:
        ticker = ticker.strip().upper()
        ts = time.time() if timestamp is None else timestamp
        with self._lock:
            prev = self._data.get(ticker)
            previous_price = prev.price if prev else price
            ref = reference_price
            if ref is None and prev is not None:
                ref = prev.reference_price
            update = PriceUpdate(ticker, price, previous_price, ts, ref)
            self._data[ticker] = update
            self._version += 1
            return update

    def get(self, ticker: str) -> PriceUpdate | None:
        with self._lock:
            return self._data.get(ticker.strip().upper())

    def get_price(self, ticker: str) -> float | None:
        update = self.get(ticker)
        return update.price if update else None

    def get_all(self) -> dict[str, PriceUpdate]:
        with self._lock:
            return dict(self._data)

    def remove(self, ticker: str) -> None:
        with self._lock:
            if self._data.pop(ticker.strip().upper(), None) is not None:
                self._version += 1

    @property
    def version(self) -> int:
        with self._lock:
            return self._version
