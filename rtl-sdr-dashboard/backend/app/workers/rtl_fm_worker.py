import asyncio
import os
import subprocess

from app.config import settings

_hls_procs: list[subprocess.Popen] = []


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

    try:
        rtl_proc = subprocess.Popen(rtl_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        mm_proc = subprocess.Popen(
            multimon_cmd,
            stdin=rtl_proc.stdout,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
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
    except FileNotFoundError:
        pass


def _run_hls_pipeline(
    rtl_cmd: list[str],
    sox_cmd: list[str],
    ffmpeg_cmd: list[str],
) -> None:
    """Blocking pipeline: rtl_fm → sox → ffmpeg → HLS segments.

    Uses subprocess.Popen (not asyncio subprocesses) so that stdout/stdin can
    be connected via real OS pipes (asyncio.StreamReader lacks fileno()).
    """
    global _hls_procs
    rtl_proc = subprocess.Popen(rtl_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    sox_proc = subprocess.Popen(
        sox_cmd, stdin=rtl_proc.stdout, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    )
    rtl_proc.stdout.close()  # allow rtl_proc to receive SIGPIPE if sox exits
    ffmpeg_proc = subprocess.Popen(ffmpeg_cmd, stdin=sox_proc.stdout, stderr=subprocess.DEVNULL)
    sox_proc.stdout.close()
    _hls_procs = [rtl_proc, sox_proc, ffmpeg_proc]
    ffmpeg_proc.wait()


async def start_hls_stream(frequency_hz: int = 98_100_000):
    """Start FM → HLS pipeline (non-blocking via executor)."""
    os.makedirs(settings.HLS_OUTPUT_DIR, exist_ok=True)
    playlist = os.path.join(settings.HLS_OUTPUT_DIR, "radio.m3u8")

    rtl_cmd = [
        "rtl_fm", "-d", settings.rtl_tcp_device, "-f", str(frequency_hz), "-M", "fm",
        "-s", "200000", "-r", "44100", "-A", "fast", "-",
    ]
    sox_cmd = [
        "sox", "-t", "raw", "-r", "44100", "-e", "signed-integer", "-b", "16",
        "-c", "1", "-", "-t", "wav", "-",
    ]
    ffmpeg_cmd = [
        "ffmpeg", "-i", "pipe:0",
        "-c:a", "aac", "-b:a", "128k",
        "-f", "hls",
        "-hls_time", "4",
        "-hls_list_size", "5",
        "-hls_flags", "delete_segments",
        playlist,
    ]

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _run_hls_pipeline, rtl_cmd, sox_cmd, ffmpeg_cmd)


async def stop_hls_stream():
    global _hls_procs
    for proc in reversed(_hls_procs):
        try:
            proc.terminate()
        except Exception:
            pass
    _hls_procs = []
