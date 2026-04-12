#!/bin/bash
# HTTP control server on port 8080.
#
# Manages both rtl_tcp (SDR data server on port 1234) and the HLS audio
# pipeline (rtl_fm → sox → ffmpeg → /tmp/hls/radio.m3u8).
#
# The backend container has no USB access and the stock Debian librtlsdr does
# not include a TCP client mode, so the pipeline MUST run here where the USB
# dongle is directly reachable.
#
# Endpoints
#   GET  /health                         – return pipeline state (running/stopped)
#   POST /audio/start?frequency_hz=N     – stop rtl_tcp, start HLS pipeline
#   POST /audio/stop                     – stop HLS pipeline, restart rtl_tcp

mkdir -p /tmp/hls

python3 - << 'PYEOF'
import logging
import os
import subprocess
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("sdr-tools")

# ── shared state (protected by _lock) ────────────────────────────────────────
_lock = threading.Lock()
_rtl_tcp_proc = None
_hls_procs: list = []  # [rtl_fm_proc, sox_proc, ffmpeg_proc]


# ── rtl_tcp helpers ──────────────────────────────────────────────────────────

def _rtl_tcp_start():
    global _rtl_tcp_proc
    if _rtl_tcp_proc and _rtl_tcp_proc.poll() is None:
        return
    log.info("Starting rtl_tcp on 0.0.0.0:1234")
    _rtl_tcp_proc = subprocess.Popen(
        ["rtl_tcp", "-a", "0.0.0.0", "-p", "1234"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _rtl_tcp_stop():
    global _rtl_tcp_proc
    if _rtl_tcp_proc and _rtl_tcp_proc.poll() is None:
        log.info("Stopping rtl_tcp")
        _rtl_tcp_proc.terminate()
        try:
            _rtl_tcp_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _rtl_tcp_proc.kill()
    _rtl_tcp_proc = None


# ── pipeline helpers ─────────────────────────────────────────────────────────

def _drain(proc, label):
    """Forward process stderr to the Python logger (runs in a daemon thread)."""
    try:
        for raw in proc.stderr:
            line = raw.rstrip(b"\n").decode(errors="replace")
            if line:
                log.info("[%s] %s", label, line)
    except Exception:
        pass


def _pipeline_stop():
    global _hls_procs
    if not _hls_procs:
        return
    log.info("Stopping HLS pipeline")
    for proc in reversed(_hls_procs):
        try:
            proc.terminate()
        except Exception:
            pass
    for proc in _hls_procs:
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    _hls_procs = []
    log.info("HLS pipeline stopped")


def _pipeline_start(freq_hz: int):
    global _hls_procs
    _pipeline_stop()
    _rtl_tcp_stop()
    time.sleep(0.3)  # brief wait for the USB device to be released

    log.info("Starting HLS pipeline: freq=%d Hz", freq_hz)

    rtl_cmd = [
        "rtl_fm", "-d", "0", "-f", str(freq_hz), "-M", "fm",
        "-s", "200000", "-r", "44100", "-A", "fast",
        "-l", "0",       # disable squelch — always pass audio through
        "-E", "deemp",   # apply FM broadcast deemphasis (50 µs Europe / 75 µs US)
        "-",
    ]
    sox_cmd = [
        "sox", "-t", "raw", "-r", "44100", "-e", "signed-integer", "-b", "16",
        "-c", "1", "-", "-t", "wav", "-",
    ]
    ffmpeg_cmd = [
        "ffmpeg", "-y",
        "-i", "pipe:0",
        "-c:a", "aac", "-b:a", "128k",
        "-f", "hls",
        "-hls_time", "4",
        "-hls_list_size", "5",
        "-hls_flags", "delete_segments",
        "-loglevel", "warning",
        "/tmp/hls/radio.m3u8",
    ]

    rtl_proc = subprocess.Popen(rtl_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    threading.Thread(target=_drain, args=(rtl_proc, "rtl_fm"), daemon=True).start()

    sox_proc = subprocess.Popen(
        sox_cmd, stdin=rtl_proc.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    threading.Thread(target=_drain, args=(sox_proc, "sox"), daemon=True).start()
    rtl_proc.stdout.close()  # let rtl_proc receive SIGPIPE when sox exits

    ffmpeg_proc = subprocess.Popen(ffmpeg_cmd, stdin=sox_proc.stdout, stderr=subprocess.PIPE)
    threading.Thread(target=_drain, args=(ffmpeg_proc, "ffmpeg"), daemon=True).start()
    sox_proc.stdout.close()

    _hls_procs = [rtl_proc, sox_proc, ffmpeg_proc]
    log.info("HLS pipeline started (pids: %s)", [p.pid for p in _hls_procs])

    # Watchdog: log clearly if any process exits unexpectedly so that the
    # "PLL not locked / no audio" symptom is immediately visible in the logs.
    for proc, label in zip(_hls_procs, ("rtl_fm", "sox", "ffmpeg")):
        threading.Thread(
            target=_watchdog, args=(proc, label), daemon=True
        ).start()


def _watchdog(proc, label):
    """Log a clear message when a pipeline process exits unexpectedly."""
    proc.wait()
    rc = proc.returncode
    if rc is not None and rc != 0:
        log.warning(
            "[%s] exited with code %d — pipeline stopped. "
            "If you see 'PLL not locked' above, run  sdr-tools/setup-host.sh  "
            "on the HOST to blacklist the kernel DVB-T module.",
            label, rc,
        )


# ── HTTP handler ─────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    def _respond(self, status: int, body: bytes):
        self.send_response(status)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path in ("/", "/health"):
            with _lock:
                running = bool(_hls_procs) and any(p.poll() is None for p in _hls_procs)
            self._respond(200, b"running\n" if running else b"stopped\n")
        else:
            self._respond(404, b"Not Found\n")

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)

        with _lock:
            if parsed.path == "/audio/start":
                freq_hz = int(qs.get("frequency_hz", ["98100000"])[0])
                _pipeline_start(freq_hz)
                self._respond(200, b"OK\n")
            elif parsed.path == "/audio/stop":
                _pipeline_stop()
                _rtl_tcp_start()
                self._respond(200, b"OK\n")
            else:
                self._respond(404, b"Not Found\n")

    def log_message(self, fmt, *args):  # suppress per-request noise
        pass


# ── main ─────────────────────────────────────────────────────────────────────

os.makedirs("/tmp/hls", exist_ok=True)

with _lock:
    _rtl_tcp_start()

log.info("Control server listening on port 8080")
server = ThreadingHTTPServer(("0.0.0.0", 8080), Handler)
server.serve_forever()
PYEOF
