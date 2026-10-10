import asyncio
from types import SimpleNamespace as NS

from app.market.cache import PriceCache
from app.market.massive_client import (
    MassiveDataSource,
    _snapshot_price,
    _snapshot_timestamp,
)


def snap(ticker, last=None, minute=None, day=None, prev=None, min_t=None, updated=None):
    return NS(
        ticker=ticker,
        last_trade=NS(price=last) if last is not None else None,
        min=NS(close=minute, timestamp=min_t) if minute is not None or min_t else None,
        day=NS(close=day) if day is not None else None,
        prev_day=NS(close=prev) if prev is not None else None,
        updated=updated,
    )


class FakeClient:
    def __init__(self, snaps=None, bars=None, snapshot_error=None):
        self.snaps = snaps or []
        self.bars = bars if bars is not None else {}
        self.snapshot_error = snapshot_error
        self.snapshot_calls = 0
        self.grouped_dates = []

    def get_snapshot_all(self, market_type, tickers=None):
        self.snapshot_calls += 1
        if self.snapshot_error:
            raise self.snapshot_error
        self.tickers = tickers
        return self.snaps

    def get_grouped_daily_aggs(self, date, adjusted=True):
        self.grouped_dates.append(date)
        return self.bars.get(len(self.grouped_dates), [])


def test_price_fallback_chain():
    assert _snapshot_price(snap("A", last=10, minute=9, day=8, prev=7)) == 10
    assert _snapshot_price(snap("A", minute=9, day=8, prev=7)) == 9
    assert _snapshot_price(snap("A", day=8, prev=7)) == 8
    assert _snapshot_price(snap("A", prev=7)) == 7
    assert _snapshot_price(snap("A")) is None


def test_timestamp_units():
    assert _snapshot_timestamp(snap("A", min_t=1_684_428_600_000)) == 1_684_428_600
    assert _snapshot_timestamp(snap("A", updated=1_605_195_918_306_274_000)) == 1_605_195_918.306274
    assert _snapshot_timestamp(snap("A", min_t=1_684_428_600)) == 1_684_428_600
    assert _snapshot_timestamp(snap("A")) > 1e9


async def test_start_polls_immediately_and_normalizes():
    cache = PriceCache()
    client = FakeClient(
        snaps=[
            snap("AAPL", last=191.5, prev=190.0, min_t=1_684_428_600_000),
            snap("MSFT", last=420.0, prev=419.0),
            snap("IGNORED", last=1.0),
        ]
    )
    src = MassiveDataSource(cache, "key", poll_interval=100, client=client)
    await src.start([" aapl", "MSFT", "msft"])
    assert src.get_tickers() == ["AAPL", "MSFT"]
    assert client.tickers == ["AAPL", "MSFT"]
    u = cache.get("AAPL")
    assert u.price == 191.5 and u.reference_price == 190.0
    assert u.timestamp == 1_684_428_600
    assert cache.get("IGNORED") is None
    await src.stop()
    await src.stop()


async def test_loop_keeps_polling_and_survives_errors():
    cache = PriceCache()
    client = FakeClient(snaps=[snap("AAPL", last=1.0)])
    src = MassiveDataSource(cache, "key", poll_interval=0.01, client=client)
    await src.start(["AAPL"])
    client.snapshot_error = RuntimeError("503")
    await asyncio.sleep(0.1)
    assert client.snapshot_calls > 2  # kept polling despite failures
    assert cache.get_price("AAPL") == 1.0  # last known price retained
    await src.stop()


async def test_403_falls_back_to_grouped_daily_once():
    cache = PriceCache()
    client = FakeClient(
        snapshot_error=RuntimeError("403 Forbidden"),
        bars={
            1: [],  # holiday
            2: [NS(ticker="AAPL", close=150.0), NS(ticker="ZZZ", close=1.0)],
            3: [NS(ticker="AAPL", close=151.0)],
        },
    )
    src = MassiveDataSource(cache, "key", poll_interval=100, client=client)
    await src.start(["AAPL"])
    assert cache.get_price("AAPL") == 150.0
    assert cache.get("ZZZ") is None
    assert cache.get("AAPL").reference_price == 150.0
    assert client.snapshot_calls == 1
    await src._poll_once()
    assert client.snapshot_calls == 1  # snapshot not retried after 403
    await src.stop()


async def test_grouped_daily_gives_up_after_a_week():
    client = FakeClient(snapshot_error=RuntimeError("403"))
    src = MassiveDataSource(PriceCache(), "key", client=client)
    await src._poll_once()  # no tickers: no-op
    assert client.snapshot_calls == 0
    src._tickers = ["AAPL"]
    await src._poll_once()
    assert len(client.grouped_dates) == 7


async def test_add_remove_ticker():
    cache = PriceCache()
    client = FakeClient(snaps=[snap("AAPL", last=1.0), snap("PYPL", last=2.0)])
    src = MassiveDataSource(cache, "key", poll_interval=100, client=client)
    await src.start(["AAPL"])
    await src.add_ticker("pypl")
    await src.add_ticker("PYPL")
    assert src.get_tickers() == ["AAPL", "PYPL"]
    await src._poll_once()
    assert cache.get_price("PYPL") == 2.0
    await src.remove_ticker("PYPL")
    assert cache.get("PYPL") is None
    assert src.get_tickers() == ["AAPL"]
    await src.stop()
