# Market Simulator

Approach and code structure for the default price source (used when `MASSIVE_API_KEY` is unset). Zero external dependencies beyond numpy; runs in-process.

Files in `backend/app/market/`:

| File | Responsibility |
|---|---|
| `seed_prices.py` | Seed prices, per-ticker `sigma`/`mu`, correlation groups and coefficients (data only) |
| `simulator.py` | `GBMSimulator` (pure math, synchronous) and `SimulatorDataSource` (asyncio wrapper implementing `MarketDataSource`) |

The split matters: `GBMSimulator.step()` is a pure, synchronous, deterministic-when-seeded function, easy to unit test. `SimulatorDataSource` only handles scheduling and writing to the `PriceCache`.

## Model: Geometric Brownian Motion

Each tick, every ticker is advanced by:

```
S(t+dt) = S(t) * exp((mu - sigma^2 / 2) * dt + sigma * sqrt(dt) * Z)
```

- `mu`: annualized drift; `sigma`: annualized volatility
- `Z`: standard normal draw, **correlated across tickers**
- `dt`: tick length as a fraction of a trading year. One 500ms tick = `0.5 / (252 * 6.5 * 3600)` ~ 8.5e-8

The log-normal form guarantees prices stay positive. With these dt values a tick moves a price by a fraction of a cent to a few cents, and moves accumulate to realistic intraday ranges (a sigma=0.25 stock moves ~1.5% over a simulated day).

## Correlation

Independent draws `z` are turned into correlated draws with a Cholesky factor `L` of the correlation matrix: `z_corr = L @ z`.

Pairwise correlation (`_pairwise_correlation`):

| Pair | rho |
|---|---|
| Both tech (AAPL, GOOGL, MSFT, AMZN, META, NVDA, NFLX) | 0.6 |
| Both finance (JPM, V) | 0.5 |
| Anything involving TSLA | 0.3 |
| Cross-sector or unknown ticker | 0.3 |

The matrix is rebuilt (O(n^2), n < 50) whenever a ticker is added or removed. All values are in `seed_prices.py`, so tuning needs no code changes. The matrix is positive definite for these constants; if constants are changed, `np.linalg.cholesky` will raise on an invalid matrix, which is the desired loud failure.

## Random events

Each ticker each tick has `event_probability` (default 0.001) of a shock: a uniform 2-5% jump, random sign. With 10 tickers at 2 ticks/s that is roughly one event every 50 seconds across the watchlist - enough drama for the demo without wrecking realism.

## Seed data and dynamic tickers

- `SEED_PRICES`: AAPL 190, GOOGL 175, MSFT 420, AMZN 185, TSLA 250, NVDA 800, META 500, JPM 195, V 280, NFLX 600.
- `TICKER_PARAMS`: per-ticker `sigma`/`mu` (TSLA 0.50, NVDA 0.40 high vol; JPM 0.18, V 0.17 low vol).
- A ticker not in the tables (user adds PYPL) gets `DEFAULT_PARAMS` (sigma 0.25, mu 0.05) and a random starting price in 50-300.

## GBMSimulator API

```python
sim = GBMSimulator(["AAPL", "MSFT"], dt=GBMSimulator.DEFAULT_DT, event_probability=0.001)
sim.step()              # -> {"AAPL": 190.02, "MSFT": 419.97}   (rounded to cents)
sim.add_ticker("PYPL")  # rebuilds Cholesky
sim.remove_ticker("MSFT")
sim.get_price("AAPL"); sim.get_tickers()
```

## SimulatorDataSource lifecycle

```
start(tickers)
  -> build GBMSimulator
  -> seed PriceCache with initial prices (SSE has data instantly)
  -> asyncio.create_task(_run_loop)

_run_loop (every update_interval = 0.5s)
  -> prices = sim.step()
  -> cache.update(ticker, price) for each

add_ticker -> sim.add_ticker + seed cache immediately
remove_ticker -> sim.remove_ticker + cache.remove
stop -> cancel task, await it
```

The loop wraps each step in try/except and logs, so one bad step never kills the stream.

## Behavior at the edges

- No market hours: the simulator runs 24/7 and does not model open/close, gaps, or weekends.
- No mean reversion: with positive drift and long uptime prices can wander far from seed values. Acceptable for a demo; restarting resets to seeds. If it becomes a problem, add weak mean reversion toward the seed price.
- Daily change %: the reference should be the seed price (session open), not the previous tick. See the "known gaps" in `MARKET_INTERFACE.md`.
- Rounding: `step()` rounds to 2 decimals for output but keeps full precision in internal state, so tiny moves are not lost to rounding.

## Testing

- Prices stay positive over 100k steps.
- With fixed `np.random.seed`/`random.seed`, `step()` is reproducible.
- Sample correlation of simulated log returns between two tech tickers is close to 0.6 over a large sample; TSLA lower.
- `event_probability=1.0` makes every tick shock; `0.0` never does.
- Adding/removing tickers keeps `get_tickers()` and Cholesky dimensions consistent.
- `SimulatorDataSource.start()` populates the cache before returning; `stop()` is idempotent.

## Demo

`backend/market_data_demo.py` is a Rich terminal demo of the simulator: `cd backend && uv run market_data_demo.py`.
