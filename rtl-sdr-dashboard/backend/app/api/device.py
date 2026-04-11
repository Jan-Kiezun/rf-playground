import asyncio
import socket

from fastapi import APIRouter

from app.config import settings

router = APIRouter(tags=["device"])


@router.get("/device/status")
async def device_status():
    """Check device availability by probing the rtl_tcp socket on the sdr-tools container."""
    host = settings.RTL_TCP_HOST
    port = settings.RTL_TCP_PORT
    try:
        loop = asyncio.get_running_loop()
        conn = await asyncio.wait_for(
            loop.run_in_executor(None, lambda: _tcp_probe(host, port)),
            timeout=3.0,
        )
        return {"connected": conn, "host": host, "port": port}
    except asyncio.TimeoutError:
        return {"connected": False, "error": "TCP probe timed out"}


def _tcp_probe(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=2.0):
            return True
    except OSError:
        return False
