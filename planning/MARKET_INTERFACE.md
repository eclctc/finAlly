# Market Data Interface

The unified Python API for stock prices. Downstream code (SSE, portfolio valuation, trade execution, watchlist) depends only on this interface and the `PriceCache`; it never knows whether prices come from Massive or the simulator.

Code lives in `backend/app/market/`. See `MASSIVE_API.md` for the real provider and `MARKET_SIMULATOR.md` for the fake one.

## Design

```
                 create_market_data_source(cache)
                   MASSIVE_API_KEY set?
                  /                     \
        MassiveDataSource         SimulatorDataSource
        (poll REST snapshot)      (GBM step every 500ms)
                  \                     /
                   writes PriceCache.update(...)
                              |
                         PriceCache  (thread-safe, in-memory, version counter)
                        /      |         \
                SSE stream   portfolio   trade execution
```

Principle: **producers push, consumers read the cache.** Consumers never call a data source for a price. This keeps one code path for reads and makes sources swappable.

## Public API

```python
from app.market import PriceCache, PriceUpdate, MarketDataSource, create_market_data_source, create_stream_router
```

### PriceUpdate (`models.py`)

Immutable dataclass: `ticker`, `price`, `previous_price`, `timestamp` (Unix seconds). Derived: `change`, `change_percent`, `direction` (`"up"|"down"|"flat"`), and `to_dict()` for JSON/SSE.

### PriceCache (`cache.py`)

| Method | Purpose |
|---|---|
| `update(ticker, price, timestamp=None) -> PriceUpdate` | Writer API. Sets `previous_price` from the prior entry (first update: equal to price). |
| `get(ticker) -> PriceUpdate \| None` | Latest for one ticker |
| `get_price(ticker) -> float \| None` | Just the float |
| `get_all() -> dict[str, PriceUpdate]` | Shallow-copy snapshot |
| `remove(ticker)` | Drop on watchlist removal |
| `version` | Monotonic counter; SSE emits only when it changes |

### MarketDataSource (`interface.py`)

```python
class MarketDataSource(ABC):
    async def start(self, tickers: list[str]) -> None: ...   # once; starts background task
    async def stop(self) -> None: ...                        # idempotent
    async def add_ticker(self, ticker: str) -> None: ...     # no-op if present
    async def remove_ticker(self, ticker: str) -> None: ...  # also clears cache entry
    def get_tickers(self) -> list[str]: ...
```

### Factory (`factory.py`)

```python
source = create_market_data_source(cache)   # unstarted
```

Rule: `MASSIVE_API_KEY` non-empty (after strip) -> `MassiveDataSource`, otherwise `SimulatorDataSource`. Selection happens once at startup.

## Usage in the FastAPI app

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.market import PriceCache, create_market_data_source, create_stream_router

cache = PriceCache()
source = create_market_data_source(cache)

@asynccontextmanager
async def lifespan(app: FastAPI):
    await source.start(load_watchlist_tickers())   # tickers from SQLite
    yield
    await source.stop()

app = FastAPI(lifespan=lifespan)
app.include_router(create_stream_router(cache))    # GET /api/stream/prices
```

Consumers:

```python
# Trade execution: price at fill time
price = cache.get_price(ticker)
if price is None:
    raise InvalidInput("No price available for ticker")

# Portfolio valuation
total = cash + sum(p.quantity * cache.get_price(p.ticker) for p in positions)

# Watchlist add / remove (service layer calls both DB and source)
await source.add_ticker("PYPL")
await source.remove_ticker("PYPL")
```

## Behavioral contract (both implementations)

1. After `start()` returns, the cache holds a price for every ticker the source can price (simulator: always; Massive: after the immediate first poll).
2. `add_ticker` makes a price available "soon": simulator immediately, Massive on the next poll. Callers needing a price right away (e.g. trading a just-added ticker) must handle `None`.
3. Tickers are normalized to upper case, stripped.
4. A failing poll/step is logged and swallowed; the background task never dies; the cache keeps the last known prices.
5. `remove_ticker` removes the cache entry, so removed tickers disappear from the SSE stream.
6. Cache timestamps are Unix seconds regardless of provider units.
7. Unknown/invalid tickers: the simulator will happily invent a price (random 50-300); Massive simply returns nothing, so the ticker never appears in the cache. Validation of ticker existence should therefore be "does the cache have a price after add" and is the caller's job.

## MassiveDataSource behavior

- One `get_snapshot_all(tickers=[...])` call per poll covers every watched ticker.
- Price = `snap.last_trade.price`; timestamp converted from ms to seconds.
- Default interval 15s (free-tier safe); configure shorter on paid plans.
- The sync `RESTClient` runs in `asyncio.to_thread`.

### Known gaps to fix (from MASSIVE_API.md)

- **Free tier**: snapshot is not available on Stocks Basic (403). Add a fallback in `_fetch`: on 403, use `get_grouped_daily_aggs` for the last trading day and write closes to the cache. Log once, not every poll.
- `lastTrade` may be absent on some plans. Fall back to `snap.min.close`, then `snap.day.close`, then `snap.prev_day.close`.
- Day change vs. tick change: `PriceUpdate.previous_price` is the previous *poll*, but the watchlist column is "daily change %". Seed it from `prev_day.close` (add an optional `session_open`/`prev_close` field to the cache) so daily change is correct for both sources. Simulator: use the seed price as the day's reference.

## Extending

New provider = new `MarketDataSource` subclass + one branch in the factory. No downstream changes. Possible future provider env vars should follow the same "set key -> use provider" pattern.

## Testing

- Unit-test each source against a real `PriceCache` (simulator with a short interval; Massive with `RESTClient` patched to return fake snapshot objects).
- Test the factory with `monkeypatch.setenv("MASSIVE_API_KEY", ...)` both set, empty, and unset.
- Integration: `GET /api/stream/prices` emits events for the default 10 tickers within 1s using the simulator.
