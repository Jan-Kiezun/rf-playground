import logging
import subprocess
import threading
from functools import lru_cache

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# Base URL of the sdr-tools control server (port 8080).
_SDR_TOOLS_URL = (
    f"http://{settings.RTL_TCP_HOST}:{settings.RTL_TCP_HEALTH_PORT}"
)


def _drain_stderr(proc: subprocess.Popen, label: str) -> None:
    """Read *proc* stderr line-by-line and forward to the Python logger.

    Runs in a daemon thread so it never blocks the main pipeline.
    """
    if proc.stderr is None:
        return
    try:
        for raw in proc.stderr:
            line = raw.rstrip("\n") if isinstance(raw, str) else raw.rstrip(b"\n").decode(errors="replace")
            if line:
                logger.info("[%s] %s", label, line)
    except Exception:
        pass


@lru_cache(maxsize=1)
def _multimon_supported_modes() -> frozenset:
    """Return the set of demodulator names supported by the installed multimon-ng.

    Calls ``multimon-ng -h`` (which exits non-zero but prints the usage block
    that includes the "Available demodulators:" line) and parses its output.
    Cached so we only probe once per process.
    """
    try:
        result = subprocess.run(
            ["multimon-ng", "-h"],
            capture_output=True, text=True, timeout=5,
        )
        output = result.stdout + result.stderr
        for line in output.splitlines():
            if "Available demodulators:" in line:
                modes_part = line.split("Available demodulators:", 1)[1]
                return frozenset(modes_part.split())
    except Exception as exc:
        logger.warning("Could not probe multimon-ng modes: %s", exc)
    return frozenset()


def run_rtl_fm_rds(connector_id: str, frequency_hz: int = 98_100_000, duration_s: int = 30):
    """Run rtl_fm and pipe to multimon-ng for RDS decoding.

    The Debian/Ubuntu package of multimon-ng (≤1.3.x) does **not** include the
    RDS demodulator — it was never part of the upstream release.  We probe the
    available modes at startup and skip gracefully if RDS is absent rather than
    spawning a pipeline that exits immediately with "invalid mode".
    """
    import json
    import redis

    r = redis.from_url(settings.REDIS_URL)

    supported = _multimon_supported_modes()
    if "RDS" not in supported:
        logger.warning(
            "multimon-ng on this system does not support RDS "
            "(available: %s). Skipping RDS pipeline for connector %s. "
            "Install a multimon-ng build with RDS support to enable this feature.",
            ", ".join(sorted(supported)) or "<none>",
            connector_id,
        )
        return

    rtl_cmd = [
        "rtl_fm", "-d", settings.rtl_tcp_device, "-f", str(frequency_hz), "-M", "fm",
        "-s", "171000", "-A", "fast", "-l", "0", "-E", "deemp", "-",
    ]
    multimon_cmd = ["multimon-ng", "-t", "raw", "-a", "RDS", "-"]

    logger.info("RDS pipeline starting: freq=%d Hz, device=%s", frequency_hz, settings.rtl_tcp_device)
    try:
        rtl_proc = subprocess.Popen(rtl_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        threading.Thread(target=_drain_stderr, args=(rtl_proc, "rtl_fm/rds"), daemon=True).start()
        mm_proc = subprocess.Popen(
            multimon_cmd,
            stdin=rtl_proc.stdout,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        threading.Thread(target=_drain_stderr, args=(mm_proc, "multimon-ng"), daemon=True).start()
        rtl_proc.stdout.close()

        import time
        start = time.time()
        for line in mm_proc.stdout:
            if time.time() - start > duration_s:
                break
            line = line.strip()
            if line:
                payload = {"type": "rds", "connector_id": connector_id, "raw": line}
                r.publish("live_data", json.dumps(payload))

        rtl_proc.terminate()
        mm_proc.terminate()
        logger.info("RDS pipeline finished (duration=%ds)", duration_s)
    except FileNotFoundError as exc:
        logger.error("RDS pipeline tool not found: %s", exc)


async def start_hls_stream(frequency_hz: int = 98_100_000) -> None:
    """Start FM → HLS pipeline by delegating to the sdr-tools control server.

    The HLS pipeline (rtl_fm → sox → ffmpeg) runs inside the sdr-tools
    container, which has direct USB access to the RTL-SDR dongle.  The backend
    container only makes an HTTP request to trigger it; the pipeline continues
    running in sdr-tools until stop_hls_stream() is called.
    """
    url = f"{_SDR_TOOLS_URL}/audio/start"
    logger.info("start_hls_stream: freq=%d Hz → %s", frequency_hz, url)
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, params={"frequency_hz": frequency_hz})
        resp.raise_for_status()
    logger.info("HLS stream started on sdr-tools")


async def stop_hls_stream() -> None:
    """Stop the FM → HLS pipeline on the sdr-tools control server."""
    url = f"{_SDR_TOOLS_URL}/audio/stop"
    logger.info("stop_hls_stream → %s", url)
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(url)
        resp.raise_for_status()
    logger.info("HLS stream stopped on sdr-tools")
