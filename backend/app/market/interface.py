"""Abstract market data source."""

from __future__ import annotations

from abc import ABC, abstractmethod


class MarketDataSource(ABC):
    @abstractmethod
    async def start(self, tickers: list[str]) -> None:
        """Start the background task; called once."""

    @abstractmethod
    async def stop(self) -> None:
        """Stop the background task; idempotent."""

    @abstractmethod
    async def add_ticker(self, ticker: str) -> None:
        """Begin tracking a ticker; no-op if already present."""

    @abstractmethod
    async def remove_ticker(self, ticker: str) -> None:
        """Stop tracking a ticker and clear its cache entry."""

    @abstractmethod
    def get_tickers(self) -> list[str]:
        """Currently tracked tickers."""
