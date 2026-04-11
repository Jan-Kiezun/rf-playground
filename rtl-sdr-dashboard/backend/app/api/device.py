import asyncio
import socket

from fastapi import APIRouter

from app.config import settings

router = APIRouter(tags=["device"])


@router.get("/device/status")
async def device_status():
    """Check device availability by probing the health-check port on the sdr-tools container.

    We probe port 8080 (a tiny HTTP server in start.sh) rather than port 1234 (rtl_tcp)
    because rtl_tcp exits whenever a TCP client disconnects — probing it directly would
    kill the SDR server on every status poll.
    """
    host = settings.RTL_TCP_HOST
    port = settings.RTL_TCP_HEALTH_PORT
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
