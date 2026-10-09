"""SSE endpoint streaming prices from the cache."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from .cache import PriceCache


def create_stream_router(cache: PriceCache, interval: float = 0.5) -> APIRouter:
    router = APIRouter()

    async def event_stream():
        last_version = -1
        while True:
            version = cache.version
            if version != last_version:
                last_version = version
                for update in cache.get_all().values():
                    yield f"data: {json.dumps(update.to_dict())}\n\n"
            await asyncio.sleep(interval)

    @router.get("/api/stream/prices")
    async def stream_prices():
        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return router
