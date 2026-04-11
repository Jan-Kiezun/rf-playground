import asyncio
import logging

from fastapi import APIRouter

from app.config import settings
from app.workers.rtl_fm_worker import start_hls_stream, stop_hls_stream

router = APIRouter(tags=["audio"])
logger = logging.getLogger(__name__)


@router.get("/audio/status")
async def audio_status():
    import os

    hls_dir = settings.HLS_OUTPUT_DIR
    playlist = os.path.join(hls_dir, "radio.m3u8")
    return {
        "hls_available": os.path.exists(playlist),
        "playlist_url": "/stream/radio.m3u8",
    }


@router.post("/audio/start")
async def start_audio_stream(frequency_hz: int = 98_100_000):
    """Start FM radio HLS stream at given frequency."""
    task = asyncio.create_task(start_hls_stream(frequency_hz))

    def _on_done(t: asyncio.Task) -> None:
        if not t.cancelled() and t.exception() is not None:
            logger.error("HLS stream task failed: %s", t.exception())

    task.add_done_callback(_on_done)
    return {"status": "starting", "frequency_hz": frequency_hz}


@router.post("/audio/stop")
async def stop_audio_stream():
    await stop_hls_stream()
    return {"status": "stopped"}
