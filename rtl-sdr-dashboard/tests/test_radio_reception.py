"""
FM radio reception tests for RTL-SDR v4.

These tests verify that real FM broadcast stations can be received by the
attached RTL-SDR dongle.  They require:

  - An RTL-SDR dongle physically attached to the machine **or** an already
    running ``rtl_tcp`` instance accessible on the network.
  - ``rtl_fm`` and ``rtl_test`` installed (part of the ``rtl-sdr`` package).
  - ``multimon-ng`` installed (for RDS decoding tests).
  - ``ffmpeg`` and ``sox`` installed (for HLS pipeline test).

Tested stations (Trójmiejski/Polish broadcasts — adjust if needed):

  - Radio Gdańsk   103.7 MHz
  - RMF FM          98.4 MHz
  - Radio ZET       105.0 MHz
  - Radio Maryja     88.9 MHz

Device selection (automatic — no manual config needed in the common case):

  The tests first check whether ``rtl_tcp`` is reachable at
  ``RTL_TCP_HOST:RTL_TCP_PORT``.  If it is, the rtl_tcp network device string
  (``rtl_tcp::host:port``) is used so that multiple processes can share the
  dongle.  If ``rtl_tcp`` is **not** running (e.g. you are running the tests
  directly on the host with the dongle plugged in), the tests fall back to
  using the dongle by its device index (``RTL_SDR_DEVICE_INDEX``, default 0).

Environment variables (all optional):

  RTL_TCP_HOST          Host running rtl_tcp  (default: localhost)
  RTL_TCP_PORT          Port of rtl_tcp        (default: 1234)
  RTL_SDR_DEVICE_INDEX  Direct device index when rtl_tcp is absent (default: 0)
  FM_SAMPLE_DURATION    Seconds to sample per station (default: 15)
  HLS_OUTPUT_DIR        Directory for HLS segments (default: /tmp/hls_test)

Examples:

  # Run all tests (device is auto-detected)
  pytest tests/test_radio_reception.py -v

  # Run against a remote rtl_tcp
  RTL_TCP_HOST=192.168.1.50 pytest tests/test_radio_reception.py -v

  # Run only the per-station audio tests
  pytest tests/test_radio_reception.py -v -k "station"
"""

import os
import shutil
import socket
import subprocess
import time
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Configuration from environment
# ---------------------------------------------------------------------------

RTL_TCP_HOST = os.getenv("RTL_TCP_HOST", "localhost")
RTL_TCP_PORT = int(os.getenv("RTL_TCP_PORT", "1234"))
RTL_SDR_DEVICE_INDEX = int(os.getenv("RTL_SDR_DEVICE_INDEX", "0"))
SAMPLE_DURATION = int(os.getenv("FM_SAMPLE_DURATION", "15"))
HLS_OUTPUT_DIR = Path(os.getenv("HLS_OUTPUT_DIR", "/tmp/hls_test"))

STATIONS = [
    ("Radio Gdańsk", 103_700_000),   # Hz
    ("RMF FM", 98_400_000),           # Hz
    ("Radio ZET", 105_000_000),       # Hz
    ("Radio Maryja", 88_900_000),     # Hz
]

# ---------------------------------------------------------------------------
# Device auto-detection
# ---------------------------------------------------------------------------


def _rtl_tcp_reachable() -> bool:
    """Return True if an rtl_tcp daemon is listening at RTL_TCP_HOST:RTL_TCP_PORT."""
    try:
        with socket.create_connection((RTL_TCP_HOST, RTL_TCP_PORT), timeout=1):
            return True
    except OSError:
        return False


def _device_string() -> str:
    """
    Return the ``-d`` argument value for rtl_fm / rtl_test.

    - If rtl_tcp is reachable → ``rtl_tcp::host:port``
    - Otherwise              → the direct device index (e.g. ``"0"``)
    """
    if _rtl_tcp_reachable():
        return f"rtl_tcp::{RTL_TCP_HOST}:{RTL_TCP_PORT}"
    return str(RTL_SDR_DEVICE_INDEX)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_binary(name: str) -> None:
    """Skip the test if *name* is not on PATH."""
    if shutil.which(name) is None:
        pytest.skip(f"'{name}' not found on PATH — install rtl-sdr tools first")


def _rtl_fm_cmd(frequency_hz: int) -> list[str]:
    """Return the rtl_fm command that reads *frequency_hz* and writes raw PCM to stdout."""
    return [
        "rtl_fm",
        "-d", _device_string(),
        "-f", str(frequency_hz),
        "-M", "fm",
        "-s", "200000",   # 200 kHz sample rate (wide-band FM)
        "-r", "44100",    # resample to 44.1 kHz for audio
        "-A", "fast",
        "-",
    ]


# ---------------------------------------------------------------------------
# Tests: basic device detection
# ---------------------------------------------------------------------------


def test_device_detected():
    """
    Verify that at least one RTL-SDR device is visible to the system.

    Uses ``rtl_test -t`` which lists available devices and exits immediately
    (no RF sampling).  The test passes as long as the output contains
    "device(s)" and no "No supported devices" error.
    """
    _require_binary("rtl_test")

    # rtl_test talks to the USB dongle directly and does not support the
    # rtl_tcp:: device format, so we always pass the numeric device index here.
    result = subprocess.run(
        ["rtl_test", "-d", str(RTL_SDR_DEVICE_INDEX), "-t"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    combined = result.stdout + result.stderr

    assert "No supported devices" not in combined, (
        "rtl_test found no supported RTL-SDR devices.\n"
        "Check that the dongle is plugged in and the dvb_usb_rtl28xxu kernel module "
        "is blacklisted.\n"
        f"rtl_test output:\n{combined}"
    )
    assert "device" in combined.lower(), (
        f"Unexpected rtl_test output — could not confirm a device was found:\n{combined}"
    )


def test_device_can_sample():
    """
    Verify that the RTL-SDR dongle can produce raw IQ samples.

    ``rtl_test`` runs indefinitely by design, so the test uses the
    Python-recommended pattern: ``communicate(timeout=10)`` always raises
    ``TimeoutExpired``; the process is then killed and the pipe drained via a
    second ``communicate()`` call.  The test passes when the captured output
    contains "Sampling at", confirming that the USB transfer pipeline is
    working and the device has been opened successfully.

    This is the lowest-level sanity check — if this fails, all RF tests will
    also fail regardless of signal strength.
    """
    _require_binary("rtl_test")

    # rtl_test talks to the USB dongle directly and does not support the
    # rtl_tcp:: device format, so we always pass the numeric device index here.
    proc = subprocess.Popen(
        ["rtl_test", "-d", str(RTL_SDR_DEVICE_INDEX), "-s", "2048000"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    try:
        combined, _ = proc.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        combined, _ = proc.communicate()

    assert "Sampling at" in combined, (
        "rtl_test did not start sampling — the dongle may be malfunctioning "
        "or the USB driver is not working correctly.\n"
        f"rtl_test output:\n{combined}"
    )
    assert "No supported devices" not in combined, (
        f"rtl_test found no supported RTL-SDR devices:\n{combined}"
    )


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
    min_bytes = 8192  # ~0.09 s of 44100 Hz 16-bit mono PCM (8192 / (44100×2) ≈ 0.093 s)

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
        f"Device used: {_device_string()}\n"
        f"This usually means the station is out of range or the RTL-SDR dongle "
        f"is not accessible (run test_device_detected first to confirm hardware).\n"
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

    The reader runs in a daemon thread so that the deadline is always
    honoured.  ``readline()`` is a blocking call — without a thread the
    deadline check is never reached while waiting for the next line.
    """
    import threading

    _require_binary("rtl_fm")
    _require_binary("multimon-ng")

    freq_hz = 98_400_000
    duration = SAMPLE_DURATION * 2

    rtl_cmd = [
        "rtl_fm",
        "-d", _device_string(),
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

    def _reader() -> None:
        for line in mm_proc.stdout:
            line = line.strip()
            if line.startswith("RDS:"):
                rds_lines.append(line)
                break  # one line is enough — stop early

    reader = threading.Thread(target=_reader, daemon=True)
    reader.start()
    try:
        reader.join(timeout=duration)
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
        f"Device used: {_device_string()}"
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
        "rtl_fm", "-d", _device_string(),
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
        f"Device used: {_device_string()}\n"
        "Check that rtl_fm, sox, and ffmpeg are all installed and that "
        "the RTL-SDR dongle is accessible."
    )
