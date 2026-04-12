import logging

from fastapi import APIRouter, HTTPException

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
    """Start FM radio HLS stream at the given frequency."""
    try:
        await start_hls_stream(frequency_hz)
    except Exception as exc:
        logger.error("Failed to start HLS stream: %s", exc)
        raise HTTPException(status_code=502, detail=f"sdr-tools unreachable: {exc}") from exc
    return {"status": "starting", "frequency_hz": frequency_hz}


@router.post("/audio/stop")
async def stop_audio_stream():
    try:
        await stop_hls_stream()
    except Exception as exc:
        logger.warning("Failed to stop HLS stream: %s", exc)
    return {"status": "stopped"}
