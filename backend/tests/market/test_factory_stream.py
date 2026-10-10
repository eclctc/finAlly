import asyncio
import json

import pytest
from fastapi import FastAPI

from app.market import (
    MarketDataSource,
    PriceCache,
    create_market_data_source,
    create_stream_router,
)
from app.market.massive_client import MassiveDataSource
from app.market.simulator import SimulatorDataSource


def test_factory_simulator_when_unset(monkeypatch):
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
    src = create_market_data_source(PriceCache())
    assert isinstance(src, SimulatorDataSource)


@pytest.mark.parametrize("value", ["", "   "])
def test_factory_simulator_when_blank(monkeypatch, value):
    monkeypatch.setenv("MASSIVE_API_KEY", value)
    assert isinstance(create_market_data_source(PriceCache()), SimulatorDataSource)


def test_factory_massive_when_set(monkeypatch):
    monkeypatch.setenv("MASSIVE_API_KEY", " abc ")
    src = create_market_data_source(PriceCache())
    assert isinstance(src, MassiveDataSource)
    assert src._api_key == "abc"


def test_both_implement_interface():
    assert issubclass(SimulatorDataSource, MarketDataSource)
    assert issubclass(MassiveDataSource, MarketDataSource)


def _route_endpoint(router):
    return next(r.endpoint for r in router.routes if r.path == "/api/stream/prices")


async def test_stream_emits_events_and_only_on_change():
    cache = PriceCache()
    cache.update("AAPL", 190.0)
    cache.update("MSFT", 420.0)
    router = create_stream_router(cache, interval=0.01)
    assert any(r.path == "/api/stream/prices" for r in router.routes)
    app = FastAPI()
    app.include_router(router)

    response = await _route_endpoint(router)()
    assert response.media_type == "text/event-stream"
    assert response.headers["cache-control"] == "no-cache"
    gen = response.body_iterator

    first = [json.loads((await gen.__anext__())[len("data: "):]) for _ in range(2)]
    assert {e["ticker"] for e in first} == {"AAPL", "MSFT"}

    # no change -> no new event
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(gen.__anext__(), timeout=0.1)

    # (cancelled __anext__ closes the generator; start a fresh one)
    response = await _route_endpoint(router)()
    gen = response.body_iterator
    await gen.__anext__()
    await gen.__anext__()
    cache.update("AAPL", 191.0)
    ev = json.loads((await asyncio.wait_for(gen.__anext__(), 1))[len("data: "):])
    assert {"AAPL", "MSFT"} >= {ev["ticker"]}
    await gen.aclose()
