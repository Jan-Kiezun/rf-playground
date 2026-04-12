import asyncio
import json
import logging

import redis.asyncio as aioredis
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.config import settings

router = APIRouter()
logger = logging.getLogger(__name__)


@router.websocket("/ws/live")
async def ws_live(websocket: WebSocket):
    await websocket.accept()
    r = aioredis.from_url(settings.REDIS_URL)
    pubsub = r.pubsub()
    await pubsub.subscribe("live_data")

    try:
        async for message in pubsub.listen():
            if message["type"] == "message":
                data = message["data"]
                if isinstance(data, bytes):
                    data = data.decode()
                await websocket.send_text(data)
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    finally:
        await pubsub.unsubscribe("live_data")
        await r.aclose()
