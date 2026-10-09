# Massive API Reference (formerly Polygon.io)

Reference for the parts of the Massive REST API that FinAlly uses to get real-time and end-of-day stock prices for multiple tickers. Sourced from massive.com/docs (checked 2026-10-09). Verify plan-specific details against the live docs before relying on them.

## Basics

| Item | Value |
|---|---|
| Base URL | `https://api.massive.com` (legacy `api.polygon.io` still works) |
| Auth | `?apiKey=KEY` query param, or `Authorization: Bearer KEY` header |
| Python client | `uv add massive` (import `from massive import RESTClient`), Python 3.9+ |
| Env var used by FinAlly | `MASSIVE_API_KEY` |
| Timestamps | Unix **milliseconds** (aggregates, snapshot `updated`/`min.t`); last-trade `t` is **nanoseconds** |
| Response envelope | `status` (`"OK"`), `request_id`, `count`/`resultsCount`, payload |
| Pagination | List endpoints return `next_url`; the Python client follows it automatically (`pagination=False` disables) |

## Plans and what they allow

| Plan | Price | Rate limit | Recency | Notes |
|---|---|---|---|---|
| Stocks Basic | free | **5 calls/min** | end of day | 2 yrs history. **No snapshot endpoints.** |
| Stocks Starter | $29/mo | unlimited | 15-min delayed | 5 yrs history, snapshots |
| Stocks Developer | $79/mo | unlimited | 15-min delayed | 10 yrs, trades |
| Stocks Advanced | $199/mo | unlimited | **real-time** | 20+ yrs |

Implication for FinAlly: the best multi-ticker call (full market snapshot) needs Starter or above. On the free tier we must fall back to end-of-day endpoints (see "Free tier strategy").

## Endpoints we use

### 1. Full Market Snapshot - latest price for many tickers in ONE call

`GET /v2/snapshot/locale/us/markets/stocks/tickers`

| Param | Notes |
|---|---|
| `tickers` | Optional comma-separated, case-sensitive (`AAPL,TSLA,GOOG`). Omit for the whole market (thousands of rows). |
| `include_otc` | Default false |

Response (abridged):

```json
{
  "status": "OK",
  "count": 2,
  "tickers": [
    {
      "ticker": "AAPL",
      "day":     {"o": 119.62, "h": 120.53, "l": 118.81, "c": 120.42, "v": 28727868, "vw": 119.72},
      "prevDay": {"o": 117.2,  "h": 119.0,  "l": 116.9,  "c": 119.44, "v": 40000000, "vw": 118.3},
      "min":     {"o": 120.4,  "h": 120.45, "l": 120.4,  "c": 120.42, "v": 5000, "av": 28727868, "t": 1684428600000, "n": 40},
      "lastTrade": {"p": 120.47, "s": 236, "x": 4, "t": 1675280958783136800},
      "lastQuote": {"P": 120.47, "S": 4, "p": 120.46, "s": 8, "t": 1675280958783136800},
      "todaysChange": 0.98,
      "todaysChangePerc": 0.82,
      "updated": 1605195918306274000
    }
  ]
}
```

Key fields: `lastTrade.p` (latest price), `prevDay.c` (previous close), `todaysChange`, `todaysChangePerc`, `day.*` (today's running bar). Snapshot data resets around 3:30am ET and repopulates from ~4am ET. `lastTrade`/`lastQuote` are plan-dependent and can be missing - code must tolerate that and fall back to `min.c` or `day.c`.

```python
from massive import RESTClient
from massive.rest.models import SnapshotMarketType

client = RESTClient(api_key="...")  # or reads MASSIVE_API_KEY from env

snaps = client.get_snapshot_all(
    market_type=SnapshotMarketType.STOCKS,
    tickers=["AAPL", "MSFT", "NVDA"],
)
for s in snaps:
    print(s.ticker, s.last_trade.price, s.prev_day.close, s.todays_change_percent)
```

Raw HTTP equivalent:

```bash
curl "https://api.massive.com/v2/snapshot/locale/us/markets/stocks/tickers?tickers=AAPL,MSFT,NVDA&apiKey=$MASSIVE_API_KEY"
```

Single ticker variant: `GET /v2/snapshot/locale/us/markets/stocks/tickers/{ticker}` (response wraps one object in `ticker`). Python: `client.get_snapshot_ticker("stocks", "AAPL")`.

### 2. Previous Day Bar - end-of-day close for one ticker

`GET /v2/aggs/ticker/{ticker}/prev?adjusted=true` (all plans)

```json
{"ticker": "AAPL", "status": "OK", "resultsCount": 1,
 "results": [{"T": "AAPL", "o": 115.55, "h": 117.59, "l": 114.13, "c": 115.97, "v": 131704427, "vw": 116.3, "t": 1605042000000}]}
```

```python
prev = client.get_previous_close_agg("AAPL")   # list with one Agg
print(prev[0].close)
```

One call per ticker - expensive on the 5/min free tier.

### 3. Daily Market Summary (grouped daily) - EOD for ALL tickers in ONE call

`GET /v2/aggs/grouped/locale/us/market/stocks/{date}?adjusted=true&include_otc=false` (all plans)

`results[]` items: `T` (ticker), `o h l c v vw n t`. Filter to the watchlist client-side. This is the free-tier workhorse: one call returns the close for every ticker.

```python
bars = client.get_grouped_daily_aggs("2026-10-08", adjusted=True)
closes = {b.ticker: b.close for b in bars if b.ticker in {"AAPL", "MSFT"}}
```

`date` must be a past trading day; weekends/holidays return empty `results`, so step back until non-empty.

### 4. Custom Bars (aggregates) - history for charts

`GET /v2/aggs/ticker/{ticker}/range/{multiplier}/{timespan}/{from}/{to}`

- `timespan`: `second|minute|hour|day|week|month|quarter|year`
- `from`/`to`: `YYYY-MM-DD` or ms timestamp; `adjusted` (default true), `sort` (`asc|desc`), `limit` (default 5000, max 50000)
- Result fields: `o h l c v vw t n`

```python
bars = list(client.list_aggs("AAPL", 1, "day", "2026-09-01", "2026-10-08", limit=50000))
for b in bars:
    print(b.timestamp, b.close)
```

### 5. Last Trade (optional)

`GET /v2/last/trade/{ticker}` - Developer plan and up. Returns `results.p` (price), `results.t` (**ns** timestamp). One ticker per call, so snapshot is preferred for multiple tickers.

## Free tier strategy (5 calls/min, no snapshot)

1. On start and once per day, call grouped daily for the most recent trading day (1 call) - gives a close for every watched ticker.
2. Poll no faster than every 15s (4 calls/min) if using per-ticker calls; with grouped daily one call per poll suffices but the value only changes once per day.
3. Treat the result as a static "last close" price. Prices will not tick in real time - the UI still works, but the simulator is the better demo experience on the free tier.

Paid tiers: poll the snapshot every 2-15s depending on plan.

## Errors

| HTTP | Meaning | Handling |
|---|---|---|
| 401 | Bad/missing key | Log and keep last cached prices |
| 403 | Endpoint not in plan (e.g. snapshot on Basic) | Log clearly; fall back to EOD endpoints |
| 429 | Rate limit hit | Skip this cycle, retry next interval |
| 5xx / network | Transient | Skip cycle |

The Python client raises on non-200. The polling loop must catch and continue; a failed poll must never kill the background task.

## Gotchas

- Tickers are case-sensitive: always upper-case before sending.
- The Python client is synchronous - call it via `asyncio.to_thread` from async code.
- Mixed units: aggregates/snapshot minute use ms; last trade/quote use ns. Normalize to Unix seconds at the boundary.
- Outside market hours `lastTrade` is the last after-hours print; `todaysChange` is relative to `prevDay.c`.
- Snapshot has no data for tickers with no trading (halted, invalid symbol): they are simply absent from `tickers`.
