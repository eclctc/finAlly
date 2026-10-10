"""Price data model shared by all market data sources."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PriceUpdate:
    ticker: str
    price: float
    previous_price: float
    timestamp: float  # Unix seconds
    reference_price: float | None = None  # day reference (prev close / session open)

    @property
    def change(self) -> float:
        return self.price - self.previous_price

    @property
    def change_percent(self) -> float:
        if self.previous_price == 0:
            return 0.0
        return self.change / self.previous_price * 100

    @property
    def day_change_percent(self) -> float:
        """Change vs. the day reference; falls back to the tick change."""
        if not self.reference_price:
            return self.change_percent
        return (self.price - self.reference_price) / self.reference_price * 100

    @property
    def direction(self) -> str:
        if self.price > self.previous_price:
            return "up"
        if self.price < self.previous_price:
            return "down"
        return "flat"

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "price": self.price,
            "previous_price": self.previous_price,
            "timestamp": self.timestamp,
            "change": round(self.change, 4),
            "change_percent": round(self.change_percent, 4),
            "day_change_percent": round(self.day_change_percent, 4),
            "direction": self.direction,
        }
