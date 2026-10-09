# FinAlly — AI Trading Workstation

A Bloomberg-style trading terminal with live streaming prices, a simulated $10k portfolio, and an LLM assistant that can analyze positions and execute trades from chat. Built entirely by coding agents as a capstone for an agentic AI coding course.

## Stack

- **Frontend**: Next.js (static export), TypeScript, Tailwind, Recharts
- **Backend**: FastAPI (uv), SSE price streaming, SQLite
- **AI**: LiteLLM → OpenRouter (Cerebras) with structured outputs
- **Market data**: built-in GBM simulator, or Massive API if a key is set
- **Deploy**: single Docker container on port 8000

## Status

- Done: backend market data (simulator, Massive client, price cache, SSE). See `planning/MARKET_DATA_SUMMARY.md`.
- Not yet built: portfolio/chat API, database, frontend, Dockerfile, scripts.

Full spec: `planning/PLAN.md`.

## Run Today

```bash
cd backend
uv sync --dev
uv run pytest
uv run market_data_demo.py   # terminal demo of the simulator
```

## Quick Start (once built)

```bash
cp .env.example .env         # add OPENROUTER_API_KEY
docker build -t finally .
docker run -v finally-data:/app/db -p 8000:8000 --env-file .env finally
# open http://localhost:8000
```

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `OPENROUTER_API_KEY` | Yes | AI chat |
| `MASSIVE_API_KEY` | No | Real market data; omit to use the simulator |
| `LLM_MOCK` | No | `true` for deterministic mock LLM responses (tests) |

## Layout

```
frontend/   Next.js app
backend/    FastAPI uv project
planning/   Spec and agent docs
test/       Playwright E2E
db/         SQLite volume mount
scripts/    Start/stop helpers
```

## License

See [LICENSE](LICENSE).
# finAlly
