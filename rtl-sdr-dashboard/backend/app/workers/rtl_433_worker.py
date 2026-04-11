import json
import subprocess

import redis

from app.config import settings


def run_rtl_433(connector_id: str, duration_s: int = 60):
    """Run rtl_433 and publish decoded packets to Redis."""
    r = redis.from_url(settings.REDIS_URL)

    tcp_device = f"rtl_tcp:{settings.RTL_TCP_HOST}:{settings.RTL_TCP_PORT}"
    cmd = ["rtl_433", "-d", tcp_device, "-F", "json", "-T", str(duration_s)]
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                decoded = json.loads(line)
            except json.JSONDecodeError:
                decoded = {"raw": line}
            payload = {"type": "weather", "connector_id": connector_id, "data": decoded}
            r.publish("live_data", json.dumps(payload))
        proc.wait()
    except FileNotFoundError:
        pass
