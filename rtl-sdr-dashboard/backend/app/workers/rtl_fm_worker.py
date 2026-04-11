import asyncio
import os
import subprocess
from typing import Optional

from app.config import settings

_stream_process: Optional[asyncio.subprocess.Process] = None
_ffmpeg_process: Optional[asyncio.subprocess.Process] = None


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


async def start_hls_stream(frequency_hz: int = 98_100_000):
    """Start FM → HLS pipeline."""
    global _stream_process, _ffmpeg_process

    os.makedirs(settings.HLS_OUTPUT_DIR, exist_ok=True)
    playlist = os.path.join(settings.HLS_OUTPUT_DIR, "radio.m3u8")

    rtl_cmd = [
        "rtl_fm", "-d", settings.rtl_tcp_device, "-f", str(frequency_hz), "-M", "fm",
        "-s", "200000", "-r", "44100", "-A", "fast", "-",
    ]
    sox_cmd = ["sox", "-t", "raw", "-r", "44100", "-e", "signed-integer", "-b", "16", "-c", "1", "-", "-t", "wav", "-"]
    ffmpeg_cmd = [
        "ffmpeg", "-i", "pipe:0",
        "-c:a", "aac", "-b:a", "128k",
        "-f", "hls",
        "-hls_time", "4",
        "-hls_list_size", "5",
        "-hls_flags", "delete_segments",
        playlist,
    ]

    rtl_proc = await asyncio.create_subprocess_exec(*rtl_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    sox_proc = await asyncio.create_subprocess_exec(*sox_cmd, stdin=rtl_proc.stdout, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    ffmpeg_proc = await asyncio.create_subprocess_exec(*ffmpeg_cmd, stdin=sox_proc.stdout, stderr=asyncio.subprocess.DEVNULL)

    _stream_process = rtl_proc
    _ffmpeg_process = ffmpeg_proc

    await ffmpeg_proc.wait()


async def stop_hls_stream():
    global _stream_process, _ffmpeg_process
    if _stream_process:
        _stream_process.terminate()
        _stream_process = None
    if _ffmpeg_process:
        _ffmpeg_process.terminate()
        _ffmpeg_process = None
