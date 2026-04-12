import json
import socket
import subprocess
import time

import redis

from app.config import settings


def run_dump1090(connector_id: str, duration_s: int = 60):
    """Run dump1090 and parse SBS-1 output."""
    r = redis.from_url(settings.REDIS_URL)

    proc = subprocess.Popen(
        ["dump1090", "--net", "--quiet"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(2)

    start = time.time()
    sock: socket.socket | None = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect(("127.0.0.1", 30003))
        sock.settimeout(1.0)
        buf = ""
        while time.time() - start < duration_s:
            try:
                chunk = sock.recv(4096).decode(errors="replace")
                buf += chunk
                lines = buf.split("\n")
                buf = lines[-1]
                for line in lines[:-1]:
                    line = line.strip()
                    if line:
                        parts = line.split(",")
                        if len(parts) >= 10:
                            payload = {
                                "type": "adsb",
                                "connector_id": connector_id,
                                "data": {
                                    "msg_type": parts[0],
                                    "icao": parts[4] if len(parts) > 4 else None,
                                    "callsign": parts[10].strip() if len(parts) > 10 else None,
                                    "altitude": parts[11] if len(parts) > 11 else None,
                                    "speed": parts[12] if len(parts) > 12 else None,
                                    "lat": parts[14] if len(parts) > 14 else None,
                                    "lon": parts[15] if len(parts) > 15 else None,
                                },
                            }
                            r.publish("live_data", json.dumps(payload))
            except socket.timeout:
                continue
    except Exception:
        pass
    finally:
        if sock is not None:
            sock.close()
        proc.terminate()
