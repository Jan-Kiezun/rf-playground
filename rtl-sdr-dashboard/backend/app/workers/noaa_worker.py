import json
import os
import subprocess
import time
import uuid

import redis

from app.config import settings


def run_noaa_apt(connector_id: str, frequency_hz: int = 137_620_000, duration_s: int = 900):
    """Capture NOAA APT satellite signal and decode to image."""
    r = redis.from_url(settings.REDIS_URL)

    wav_path = f"/tmp/noaa_{uuid.uuid4().hex}.wav"
    img_path = os.path.join(settings.HLS_OUTPUT_DIR, f"noaa_{uuid.uuid4().hex}.png")

    record_cmd = [
        "rtl_fm", "-f", str(frequency_hz), "-s", "60000", "-g", "50",
        "-", "|", "sox", "-t", "raw", "-r", "60000", "-e", "signed-integer",
        "-b", "16", "-c", "1", "-", "-r", "11025", "-t", "wav", wav_path,
        "rate", "11025",
    ]

    try:
        rtl_proc = subprocess.Popen(
            ["rtl_fm", "-f", str(frequency_hz), "-s", "60000", "-g", "50", "-"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
        sox_proc = subprocess.Popen(
            ["sox", "-t", "raw", "-r", "60000", "-e", "signed-integer", "-b", "16",
             "-c", "1", "-", "-r", "11025", wav_path],
            stdin=rtl_proc.stdout, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        rtl_proc.stdout.close()
        time.sleep(duration_s)
        rtl_proc.terminate()
        sox_proc.wait()
    except FileNotFoundError:
        return

    if not os.path.exists(wav_path):
        return

    try:
        subprocess.run(["noaa-apt", wav_path, "-o", img_path], check=True, timeout=120)
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return
    finally:
        if os.path.exists(wav_path):
            os.remove(wav_path)

    payload = {
        "type": "noaa_image",
        "connector_id": connector_id,
        "image_path": img_path,
    }
    r.publish("live_data", json.dumps(payload))
