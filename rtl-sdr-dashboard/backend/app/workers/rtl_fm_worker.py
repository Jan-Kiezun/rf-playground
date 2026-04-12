import asyncio
import logging
import os
import subprocess
import threading

from app.config import settings

logger = logging.getLogger(__name__)

_hls_procs: list[subprocess.Popen] = []


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


def run_rtl_fm_rds(connector_id: str, frequency_hz: int = 98_100_000, duration_s: int = 30):
    """Run rtl_fm and pipe to multimon-ng for RDS decoding."""
    import json
    import redis

    r = redis.from_url(settings.REDIS_URL)

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


def _run_hls_pipeline(
    rtl_cmd: list[str],
    sox_cmd: list[str],
    ffmpeg_cmd: list[str],
) -> None:
    """Blocking pipeline: rtl_fm → sox → ffmpeg → HLS segments.

    Uses subprocess.Popen (not asyncio subprocesses) so that stdout/stdin can
    be connected via real OS pipes (asyncio.StreamReader lacks fileno()).
    Stderr from every stage is captured and forwarded to the Python logger so
    failures are visible in ``docker compose logs backend``.
    """
    global _hls_procs

    logger.info("HLS pipeline starting")
    logger.info("  rtl_fm  : %s", " ".join(rtl_cmd))
    logger.info("  sox     : %s", " ".join(sox_cmd))
    logger.info("  ffmpeg  : %s", " ".join(ffmpeg_cmd))

    rtl_proc = subprocess.Popen(rtl_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    threading.Thread(target=_drain_stderr, args=(rtl_proc, "rtl_fm"), daemon=True).start()

    sox_proc = subprocess.Popen(
        sox_cmd, stdin=rtl_proc.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    threading.Thread(target=_drain_stderr, args=(sox_proc, "sox"), daemon=True).start()
    rtl_proc.stdout.close()  # allow rtl_proc to receive SIGPIPE if sox exits

    ffmpeg_proc = subprocess.Popen(ffmpeg_cmd, stdin=sox_proc.stdout, stderr=subprocess.PIPE)
    threading.Thread(target=_drain_stderr, args=(ffmpeg_proc, "ffmpeg"), daemon=True).start()
    sox_proc.stdout.close()

    _hls_procs = [rtl_proc, sox_proc, ffmpeg_proc]
    rc = ffmpeg_proc.wait()
    logger.info("HLS pipeline ended (ffmpeg exit code=%d)", rc)

    rtl_rc = rtl_proc.poll()
    sox_rc = sox_proc.poll()
    if rtl_rc is not None:
        logger.info("rtl_fm exit code=%d", rtl_rc)
    if sox_rc is not None:
        logger.info("sox exit code=%d", sox_rc)


async def start_hls_stream(frequency_hz: int = 98_100_000):
    """Start FM → HLS pipeline (non-blocking via executor)."""
    os.makedirs(settings.HLS_OUTPUT_DIR, exist_ok=True)
    playlist = os.path.join(settings.HLS_OUTPUT_DIR, "radio.m3u8")

    logger.info(
        "start_hls_stream: freq=%d Hz, playlist=%s, device=%s",
        frequency_hz, playlist, settings.rtl_tcp_device,
    )

    rtl_cmd = [
        "rtl_fm", "-d", settings.rtl_tcp_device, "-f", str(frequency_hz), "-M", "fm",
        "-s", "200000", "-r", "44100", "-A", "fast", "-",
    ]
    sox_cmd = [
        "sox", "-t", "raw", "-r", "44100", "-e", "signed-integer", "-b", "16",
        "-c", "1", "-", "-t", "wav", "-",
    ]
    ffmpeg_cmd = [
        "ffmpeg", "-y",          # overwrite existing playlist/segments without prompting
        "-i", "pipe:0",
        "-c:a", "aac", "-b:a", "128k",
        "-f", "hls",
        "-hls_time", "4",
        "-hls_list_size", "5",
        "-hls_flags", "delete_segments",
        "-loglevel", "warning",  # suppress per-frame noise, keep warnings/errors
        playlist,
    ]

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _run_hls_pipeline, rtl_cmd, sox_cmd, ffmpeg_cmd)


async def stop_hls_stream():
    global _hls_procs
    logger.info("stop_hls_stream: terminating %d process(es)", len(_hls_procs))
    for proc in reversed(_hls_procs):
        try:
            proc.terminate()
        except Exception:
            pass
    _hls_procs = []
