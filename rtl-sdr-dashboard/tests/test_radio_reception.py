"""
FM radio reception tests for RTL-SDR v4.

These tests verify that real FM broadcast stations can be received by the
attached RTL-SDR dongle.  They require:

  - An RTL-SDR dongle physically attached to the machine **or** an already
    running ``rtl_tcp`` instance accessible on the network.
  - ``rtl_fm`` installed (part of the ``rtl-sdr`` package).
  - ``multimon-ng`` installed (for RDS decoding tests).
  - ``ffmpeg`` and ``sox`` installed (for HLS pipeline test).

Tested stations (Trójmiejski/Polish broadcasts — adjust if needed):

  - Radio Gdańsk   103.7 MHz
  - RMF FM          98.4 MHz
  - Radio ZET       105.0 MHz
  - Radio Maryja     88.9 MHz

Environment variables (all optional — defaults work with a local rtl_tcp):

  RTL_TCP_HOST          Host running rtl_tcp  (default: localhost)
  RTL_TCP_PORT          Port of rtl_tcp        (default: 1234)
  FM_SAMPLE_DURATION    Seconds to sample per station (default: 15)
  HLS_OUTPUT_DIR        Directory for HLS segments (default: /tmp/hls_test)

Skip the whole module when rtl_fm is not found:

  pytest tests/test_radio_reception.py

Skip only hardware tests (run everything else):

  pytest tests/test_radio_reception.py -k "not station"
"""

import os
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Configuration from environment
# ---------------------------------------------------------------------------

RTL_TCP_HOST = os.getenv("RTL_TCP_HOST", "localhost")
RTL_TCP_PORT = int(os.getenv("RTL_TCP_PORT", "1234"))
SAMPLE_DURATION = int(os.getenv("FM_SAMPLE_DURATION", "15"))
HLS_OUTPUT_DIR = Path(os.getenv("HLS_OUTPUT_DIR", "/tmp/hls_test"))

RTL_TCP_DEVICE = f"rtl_tcp::{RTL_TCP_HOST}:{RTL_TCP_PORT}"

STATIONS = [
    ("Radio Gdańsk", 103_700_000),
    ("RMF FM", 98_400_000),
    ("Radio ZET", 105_000_000),
    ("Radio Maryja", 88_900_000),
]

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _require_binary(name: str) -> None:
    """Skip the test if *name* is not on PATH."""
    if shutil.which(name) is None:
        pytest.skip(f"'{name}' not found on PATH — install rtl-sdr tools first")


def _rtl_fm_cmd(frequency_hz: int) -> list[str]:
    """Return the rtl_fm command that reads *frequency_hz* and writes raw PCM to stdout."""
    return [
        "rtl_fm",
        "-d", RTL_TCP_DEVICE,
        "-f", str(frequency_hz),
        "-M", "fm",
        "-s", "200000",   # 200 kHz sample rate (wide-band FM)
        "-r", "44100",    # resample to 44.1 kHz for audio
        "-A", "fast",
        "-",
    ]


# ---------------------------------------------------------------------------
# Tests: per-station raw audio reception
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("station_name,frequency_hz", STATIONS, ids=[s[0] for s in STATIONS])
def test_station_produces_audio(station_name: str, frequency_hz: int):
    """
    Verify that ``rtl_fm`` can receive audio from *station_name* at *frequency_hz*.

    The test runs ``rtl_fm`` for up to ``SAMPLE_DURATION`` seconds and asserts
    that at least 8 192 bytes of raw PCM are received, which corresponds to
    ~0.05 seconds of 16-bit mono 44.1 kHz audio — a very conservative threshold
    that rules out complete signal absence while still finishing quickly.
    """
    _require_binary("rtl_fm")

    cmd = _rtl_fm_cmd(frequency_hz)
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError:
        pytest.skip("rtl_fm not found")

    collected: list[bytes] = []
    deadline = time.monotonic() + SAMPLE_DURATION
    min_bytes = 8192  # ~0.05 s of 44100 Hz 16-bit mono PCM

    try:
        while time.monotonic() < deadline:
            chunk = proc.stdout.read(4096)
            if not chunk:
                break
            collected.append(chunk)
            total = sum(len(c) for c in collected)
            if total >= min_bytes:
                break  # enough data — pass early
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

    total_bytes = sum(len(c) for c in collected)
    stderr_output = proc.stderr.read().decode(errors="replace")

    assert total_bytes >= min_bytes, (
        f"[{station_name} @ {frequency_hz / 1e6:.1f} MHz] "
        f"Expected ≥{min_bytes} bytes of PCM audio but got {total_bytes} bytes.\n"
        f"This usually means the station is out of range or the RTL-SDR dongle "
        f"is not connected / rtl_tcp is not running at {RTL_TCP_HOST}:{RTL_TCP_PORT}.\n"
        f"rtl_fm stderr:\n{stderr_output[-2000:]}"
    )


# ---------------------------------------------------------------------------
# Test: RDS data decoding (multimon-ng) — single station, longer window
# ---------------------------------------------------------------------------


def test_rds_decoding_rmf_fm():
    """
    Verify that RDS frames can be decoded from RMF FM (98.4 MHz).

    Runs ``rtl_fm | multimon-ng -a RDS`` for up to ``SAMPLE_DURATION * 2``
    seconds and checks that at least one ``RDS:`` line appears in the output.
    RDS data bursts every ~87 ms, so within 30 s on a strong signal there
    should always be output.
    """
    _require_binary("rtl_fm")
    _require_binary("multimon-ng")

    freq_hz = 98_400_000
    duration = SAMPLE_DURATION * 2

    rtl_cmd = [
        "rtl_fm",
        "-d", RTL_TCP_DEVICE,
        "-f", str(freq_hz),
        "-M", "fm",
        "-s", "171000",  # narrow sample rate preferred by multimon-ng
        "-A", "fast",
        "-l", "0",
        "-E", "deemp",
        "-",
    ]
    mm_cmd = ["multimon-ng", "-t", "raw", "-a", "RDS", "-"]

    try:
        rtl_proc = subprocess.Popen(rtl_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        mm_proc = subprocess.Popen(
            mm_cmd,
            stdin=rtl_proc.stdout,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        rtl_proc.stdout.close()
    except FileNotFoundError as exc:
        pytest.skip(f"Required binary not found: {exc}")

    rds_lines: list[str] = []
    deadline = time.monotonic() + duration

    try:
        while time.monotonic() < deadline:
            line = mm_proc.stdout.readline()
            if not line:
                break
            line = line.strip()
            if line.startswith("RDS:"):
                rds_lines.append(line)
                break  # one line is enough — pass early
    finally:
        rtl_proc.terminate()
        mm_proc.terminate()
        for p in (rtl_proc, mm_proc):
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()

    assert rds_lines, (
        f"No RDS frames decoded from RMF FM (98.4 MHz) within {duration} s.\n"
        "This can mean the signal is too weak for RDS decoding even though audio "
        "reception is fine, or that multimon-ng is not receiving data from rtl_fm.\n"
        f"rtl_tcp endpoint: {RTL_TCP_HOST}:{RTL_TCP_PORT}"
    )


# ---------------------------------------------------------------------------
# Test: HLS pipeline produces playlist (no audio device required on host)
# ---------------------------------------------------------------------------


def test_hls_pipeline_creates_playlist():
    """
    Verify that the ``rtl_fm → sox → ffmpeg`` HLS pipeline starts up and
    writes a ``radio.m3u8`` playlist file within 20 seconds.

    This exercises the full audio chain used by the Radio Player page.
    Requires ``rtl_fm``, ``sox``, and ``ffmpeg`` on PATH.
    """
    _require_binary("rtl_fm")
    _require_binary("sox")
    _require_binary("ffmpeg")

    freq_hz = 98_400_000  # RMF FM
    hls_dir = HLS_OUTPUT_DIR / "hls_pipeline_test"
    hls_dir.mkdir(parents=True, exist_ok=True)
    playlist = hls_dir / "radio.m3u8"

    rtl_cmd = [
        "rtl_fm", "-d", RTL_TCP_DEVICE,
        "-f", str(freq_hz), "-M", "fm",
        "-s", "200000", "-r", "44100", "-A", "fast", "-",
    ]
    sox_cmd = [
        "sox", "-t", "raw", "-r", "44100", "-e", "signed-integer", "-b", "16",
        "-c", "1", "-", "-t", "wav", "-",
    ]
    ffmpeg_cmd = [
        "ffmpeg", "-y", "-i", "pipe:0",
        "-c:a", "aac", "-b:a", "128k",
        "-f", "hls",
        "-hls_time", "4",
        "-hls_list_size", "5",
        "-hls_flags", "delete_segments",
        str(playlist),
    ]

    procs: list[subprocess.Popen] = []
    try:
        rtl_proc = subprocess.Popen(rtl_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        sox_proc = subprocess.Popen(
            sox_cmd, stdin=rtl_proc.stdout, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
        rtl_proc.stdout.close()
        ffmpeg_proc = subprocess.Popen(
            ffmpeg_cmd, stdin=sox_proc.stdout, stderr=subprocess.DEVNULL,
        )
        sox_proc.stdout.close()
        procs = [rtl_proc, sox_proc, ffmpeg_proc]

        # Wait up to 20 s for the playlist to appear
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if playlist.exists() and playlist.stat().st_size > 0:
                break
            time.sleep(0.5)

    finally:
        for p in reversed(procs):
            try:
                p.terminate()
            except Exception:
                pass
        for p in procs:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()

    assert playlist.exists() and playlist.stat().st_size > 0, (
        f"HLS playlist was not created at {playlist} within 20 s.\n"
        "Check that rtl_fm, sox, and ffmpeg are all installed and that "
        f"rtl_tcp is running at {RTL_TCP_HOST}:{RTL_TCP_PORT}."
    )
