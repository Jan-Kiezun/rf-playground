#!/usr/bin/env python3
"""
RTL-SDR v4 Multi-Mode Image Scanner
====================================
Monitors multiple frequencies simultaneously and decodes image-containing
signals: NOAA APT weather satellites, SSTV, and APRS (the mystery 144.8 MHz).

Dependencies:
    pip install -r requirements.txt

System packages (Debian/Ubuntu):
    sudo apt install rtl-sdr librtlsdr-dev sox multimon-ng direwolf
"""

import datetime
import logging
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time
import wave
from enum import IntEnum
from pathlib import Path
from typing import Callable, Optional

import numpy as np

try:
    from PIL import Image

    HAS_PIL = True
except ImportError:
    HAS_PIL = False

try:
    import scipy.signal as sp_signal

    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False

# ──────────────────────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────────────────────

OUTPUT_DIR = Path(__file__).parent / "output" / "images"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

LOG_LEVEL = logging.DEBUG

NOAA_FREQS_HZ = {
    "NOAA-15": 137_620_000,
    "NOAA-18": 137_912_500,
    "NOAA-19": 137_100_000,
}
SSTV_FREQS_HZ = {
    "SSTV-2m": 145_500_000,
    "SSTV-20m": 14_230_000,
}
APRS_FREQ_HZ = 144_800_000
SAMPLE_RATE = 2_048_000
APT_SAMPLE_RATE = 20_800
AUDIO_RATE = 48_000
NOAA_RECORD_DURATION = 900  # seconds per pass attempt

# ──────────────────────────────────────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(OUTPUT_DIR.parent / "sdr_scanner.log"),
    ],
)
log = logging.getLogger("sdr_scanner")

# ──────────────────────────────────────────────────────────────────────────────
# SDR Scheduler
# ──────────────────────────────────────────────────────────────────────────────
# The RTL-SDR is a single physical device.  A cooperative scheduler manages
# access so every decoder gets regular turns without starvation.
#
# Priorities (lower number = higher priority):
#   0 = APRS     — short 30-second slices, re-queues itself immediately
#   1 = NOAA     — long 900-second blocks (only when satellite is overhead)
#   2 = SSTV     — medium 120-second slices
#   3 = Scanner  — opportunistic, only runs when nothing else is waiting
#
# Each task is a callable submitted via SDRScheduler.submit().
# The scheduler runs one task at a time on a dedicated worker thread.


class Priority(IntEnum):
    APRS = 0
    NOAA = 1
    SSTV = 2
    SCANNER = 3


class SDRTask:
    _seq = 0
    _seq_lock = threading.Lock()

    def __init__(self, priority: Priority, fn: Callable, name: str = ""):
        with SDRTask._seq_lock:
            SDRTask._seq += 1
            self.seq = SDRTask._seq
        self.priority = priority
        self.fn = fn
        self.name = name
        self._done = threading.Event()
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def wait(self, timeout: Optional[float] = None):
        self._done.wait(timeout=timeout)

    # Make the task sortable for heapq
    def __lt__(self, other):
        if self.priority != other.priority:
            return self.priority < other.priority
        return self.seq < other.seq


class SDRScheduler:
    """
    Priority-queue based SDR device scheduler.
    Submit SDRTask objects; the scheduler runs them one at a time
    in priority order on a background thread.
    """

    def __init__(self):
        import heapq

        self._heap: list[SDRTask] = []
        self._heap_lock = threading.Lock()
        self._wakeup = threading.Event()
        self._stop = threading.Event()
        self._worker = threading.Thread(
            target=self._run, daemon=True, name="sdr-scheduler"
        )
        self._heapq = heapq

    def start(self):
        self._worker.start()
        log.info("[Scheduler] SDR scheduler started")

    def stop(self):
        self._stop.set()
        self._wakeup.set()

    def submit(self, task: SDRTask):
        with self._heap_lock:
            self._heapq.heappush(self._heap, task)
        self._wakeup.set()
        log.debug(
            "[Scheduler] Queued %s (priority=%s, queue_len=%d)",
            task.name,
            task.priority.name,
            len(self._heap),
        )

    def queue_depth(self) -> int:
        with self._heap_lock:
            return len(self._heap)

    def _run(self):
        while not self._stop.is_set():
            self._wakeup.wait()
            self._wakeup.clear()

            while True:
                with self._heap_lock:
                    if not self._heap:
                        break
                    task = self._heapq.heappop(self._heap)

                if task._cancelled:
                    task._done.set()
                    continue

                log.debug(
                    "[Scheduler] Running %s (priority=%s)",
                    task.name,
                    task.priority.name,
                )
                try:
                    task.fn()
                except Exception as exc:
                    log.exception("[Scheduler] Task %s raised: %s", task.name, exc)
                finally:
                    task._done.set()


# Global scheduler instance
scheduler = SDRScheduler()


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────


def timestamp_str() -> str:
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


def rtl_fm_cmd(
    freq_hz: int,
    sample_rate: int,
    audio_rate: int,
    modulation: str = "fm",
    gain: int = 40,
    squelch: int = 0,
) -> list[str]:
    return [
        "rtl_fm",
        "-d",
        "0",
        "-f",
        str(freq_hz),
        "-M",
        modulation,
        "-s",
        str(sample_rate),
        "-r",
        str(audio_rate),
        "-g",
        str(gain),
        "-l",
        str(squelch),
        "-F",
        "9",
        "-",
    ]


def sox_to_wav_cmd(audio_rate: int) -> list[str]:
    return [
        "sox",
        "-t",
        "raw",
        "-r",
        str(audio_rate),
        "-e",
        "signed-integer",
        "-b",
        "16",
        "-c",
        "1",
        "-",
        "-t",
        "wav",
        "-",
    ]


def kill_procs(*procs):
    for p in procs:
        try:
            p.terminate()
        except Exception:
            pass
    for p in procs:
        try:
            p.wait(timeout=3)
        except Exception:
            try:
                p.kill()
            except Exception:
                pass


def check_external_tools() -> bool:
    ok = True
    for tool in ("rtl_fm", "sox", "multimon-ng"):
        if subprocess.run(["which", tool], capture_output=True).returncode != 0:
            log.warning("External tool not found: %s", tool)
            ok = False
    if subprocess.run(["which", "direwolf"], capture_output=True).returncode != 0:
        log.info("direwolf not found – will use multimon-ng for APRS")
    return ok


# ──────────────────────────────────────────────────────────────────────────────
# APRS Decoder  (144.800 MHz — the mystery signal)
# ──────────────────────────────────────────────────────────────────────────────


class APRSDecoder:
    """
    Decode APRS on 144.800 MHz.

    Runs in 30-second slices so NOAA passes can interleave.
    A 30-second window will catch ~1-2 beacons on average given the
    15-30s beacon interval of the mystery transmitter.

    After each slice the decoder immediately re-queues itself at
    Priority.APRS so it runs as soon as the device is free again.
    """

    SLICE_SECONDS = 30

    def __init__(self, freq_hz: int = APRS_FREQ_HZ):
        self.freq_hz = freq_hz
        self._stop = threading.Event()
        self._use_direwolf = (
            subprocess.run(["which", "direwolf"], capture_output=True).returncode == 0
        )
        log.info(
            "[APRS] Backend: %s", "direwolf" if self._use_direwolf else "multimon-ng"
        )

    def start(self):
        self._stop.clear()
        self._enqueue()
        log.info("[APRS] Decoder started @ %.3f MHz", self.freq_hz / 1e6)

    def stop(self):
        self._stop.set()

    def _enqueue(self):
        if self._stop.is_set():
            return
        task = SDRTask(Priority.APRS, self._run_slice, name=f"APRS-{timestamp_str()}")
        scheduler.submit(task)

    def _run_slice(self):
        if self._stop.is_set():
            return
        try:
            if self._use_direwolf:
                self._listen_direwolf()
            else:
                self._listen_multimon()
        except Exception as exc:
            log.warning("[APRS] Slice error: %s", exc)
            time.sleep(2)
        finally:
            # Always re-queue for the next slice
            self._enqueue()

    # ------------------------------------------------------------------
    def _listen_direwolf(self):
        log.debug("[APRS] direwolf slice (%ds)", self.SLICE_SECONDS)

        dw_conf = tempfile.NamedTemporaryFile(mode="w", suffix=".conf", delete=False)
        dw_conf.write("ADEVICE null null\nCHANNEL 0\nMYCALL NOCALL\nMODEM 1200\n")
        dw_conf.flush()
        dw_conf_path = dw_conf.name
        dw_conf.close()

        cmd_fm = ["timeout", str(self.SLICE_SECONDS)] + rtl_fm_cmd(
            self.freq_hz, sample_rate=256_000, audio_rate=48_000, modulation="fm"
        )
        cmd_sox = [
            "sox",
            "-t",
            "raw",
            "-r",
            "48000",
            "-e",
            "signed-integer",
            "-b",
            "16",
            "-c",
            "1",
            "-",
            "-t",
            "wav",
            "-r",
            "48000",
            "-",
        ]
        cmd_dw = [
            "direwolf",
            "-r",
            "48000",
            "-b",
            "16",
            "-c",
            dw_conf_path,
            "-t",
            "0",
            "-q",
            "d",
            "-",
        ]

        p1 = subprocess.Popen(cmd_fm, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        p2 = subprocess.Popen(
            cmd_sox, stdin=p1.stdout, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
        )
        p3 = subprocess.Popen(
            cmd_dw, stdin=p2.stdout, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
        )
        p1.stdout.close()
        p2.stdout.close()

        try:
            for raw_line in p3.stdout:
                line = raw_line.decode(errors="replace").strip()
                if not line:
                    continue
                # Filter out direwolf startup banner lines
                if any(
                    s in line
                    for s in [
                        "Dire Wolf",
                        "support for",
                        "Reading config",
                        "Audio input",
                        "Audio out",
                        "Channel 0:",
                        "PTT not",
                        "Ready to accept",
                        "AGW",
                        "KISS",
                    ]
                ):
                    log.debug("[APRS/dw-info] %s", line)
                    continue
                log.info("[APRS] %s", line)
                self._process_packet(line)
                if self._stop.is_set():
                    break
        finally:
            kill_procs(p1, p2, p3)
            Path(dw_conf_path).unlink(missing_ok=True)

    # ------------------------------------------------------------------
    def _listen_multimon(self):
        log.debug("[APRS] multimon-ng slice (%ds)", self.SLICE_SECONDS)

        cmd_fm = ["timeout", str(self.SLICE_SECONDS)] + rtl_fm_cmd(
            self.freq_hz, sample_rate=256_000, audio_rate=AUDIO_RATE, modulation="fm"
        )
        cmd_sox = sox_to_wav_cmd(AUDIO_RATE)
        cmd_mm = [
            "multimon-ng",
            "-t",
            "wav",
            "-a",
            "AFSK1200",
            "--timestamp",
            "-",
        ]

        p1 = subprocess.Popen(cmd_fm, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        p2 = subprocess.Popen(
            cmd_sox, stdin=p1.stdout, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
        )
        p3 = subprocess.Popen(
            cmd_mm, stdin=p2.stdout, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
        )
        p1.stdout.close()
        p2.stdout.close()

        try:
            for raw_line in p3.stdout:
                line = raw_line.decode(errors="replace").strip()
                if not line:
                    continue
                log.info("[APRS/multimon] %s", line)
                if "AFSK1200:" in line:
                    self._process_packet(line.split("AFSK1200:", 1)[-1].strip())
                if self._stop.is_set():
                    break
        finally:
            kill_procs(p1, p2, p3)

    # ------------------------------------------------------------------
    def _process_packet(self, line: str):
        aprs_log = OUTPUT_DIR.parent / "aprs_packets.log"
        with open(aprs_log, "a") as f:
            f.write(f"{timestamp_str()} | {line}\n")
        self._try_extract_image(line)

    @staticmethod
    def _try_extract_image(line: str):
        for match in re.finditer(r"[A-Za-z0-9+/]{60,}={0,2}", line):
            try:
                import base64

                data = base64.b64decode(match.group(0))
                if data[:2] == b"\xff\xd8":
                    ext = "jpg"
                elif data[:4] == b"\x89PNG":
                    ext = "png"
                else:
                    continue
                out = OUTPUT_DIR / f"aprs_image_{timestamp_str()}.{ext}"
                out.write_bytes(data)
                log.info("[APRS] Extracted embedded image → %s", out)
            except Exception:
                pass


# ──────────────────────────────────────────────────────────────────────────────
# NOAA APT Decoder  — replace the existing NOAADecoder class with this
# ──────────────────────────────────────────────────────────────────────────────


class NOAADecoder:
    """
    Decode NOAA APT weather-satellite images.

    APT signal chain:
        Satellite RF (137 MHz, AM)
          → rtl_fm -M am  →  audio at APT_AUDIO_RATE  (2400 Hz subcarrier present)
          → sox saves WAV
          → bandpass filter around 2400 Hz subcarrier
          → Hilbert envelope detection
          → decimate to 4160 Sa/s  (2 × 2080 pixels/line)
          → reshape into image lines
          → save PNG

    Key rates:
        APT_AUDIO_RATE  = 48 000 Sa/s   ← must be >> 2×2400 Hz, use 48k
        pixel rate      =  4 160 Sa/s   (2080 px/line × 2 lines/s)
        decimation      = 48000 / 4160  ≈ 11 (use resample, not slice)
    """

    PIXELS_PER_LINE = 2080
    SUBCARRIER_HZ = 2400
    LINE_RATE = 2  # lines per second
    # Record at 48 kHz so the 2400 Hz subcarrier is well-resolved
    AUDIO_RATE = 48_000

    def __init__(self, name: str, freq_hz: int):
        self.name = name
        self.freq_hz = freq_hz

    def submit_pass(self) -> "SDRTask":
        task = SDRTask(Priority.NOAA, self._run_pass, name=f"NOAA-{self.name}")
        scheduler.submit(task)
        log.info(
            "[NOAA] Pass queued: %s @ %.3f MHz (queue depth=%d)",
            self.name,
            self.freq_hz / 1e6,
            scheduler.queue_depth(),
        )
        return task

    # ------------------------------------------------------------------
    def _run_pass(self):
        wav_path = OUTPUT_DIR.parent / f"apt_{self.name}_{timestamp_str()}.wav"
        try:
            self._record_to_wav(wav_path, NOAA_RECORD_DURATION)
            img = self._decode_apt_wav(wav_path)
            if img is not None:
                out = OUTPUT_DIR / f"noaa_{self.name}_{timestamp_str()}.png"
                img.save(str(out))
                log.info("[NOAA] ✓ Saved image → %s", out)
            else:
                log.warning("[NOAA] No image decoded from %s", wav_path)
        except Exception as exc:
            log.exception("[NOAA] Pass error: %s", exc)
        finally:
            wav_path.unlink(missing_ok=True)

    # ------------------------------------------------------------------
    def _record_to_wav(self, path: Path, duration: float):
        """
        Record AM-demodulated audio at 48 kHz.
        48 kHz gives 20× oversampling of the 2400 Hz subcarrier,
        which is necessary for clean envelope detection.
        """
        log.info(
            "[NOAA] Recording %ds @ %.3f MHz (AM, %d Hz audio)…",
            duration,
            self.freq_hz / 1e6,
            self.AUDIO_RATE,
        )

        cmd_fm = [
            "timeout",
            str(int(duration)),
            "rtl_fm",
            "-d",
            "0",
            "-f",
            str(self.freq_hz),
            "-M",
            "am",  # AM demodulation
            "-s",
            "1200000",  # 1.2 MS/s input (safe for v4)
            "-r",
            str(self.AUDIO_RATE),  # 48 000 Sa/s output
            "-g",
            "40",
            "-l",
            "0",
            "-F",
            "9",
            "-",
        ]
        cmd_sox = [
            "sox",
            "-t",
            "raw",
            "-r",
            str(self.AUDIO_RATE),
            "-e",
            "signed-integer",
            "-b",
            "16",
            "-c",
            "1",
            "-",
            str(path),
        ]

        p1 = subprocess.Popen(cmd_fm, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        p2 = subprocess.Popen(
            cmd_sox,
            stdin=p1.stdout,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        p1.stdout.close()
        p2.wait()
        rtl_err = p1.stderr.read().decode(errors="replace")
        p1.wait()

        for line in rtl_err.splitlines():
            if line.strip():
                log.debug("[NOAA/rtl_fm] %s", line.strip())

        size = path.stat().st_size if path.exists() else 0
        if size < 1024:
            hint = ""
            if "usb_claim_interface error" in rtl_err:
                hint = " (device busy)"
            elif "No supported" in rtl_err or "Failed to open" in rtl_err:
                hint = " (device not found)"
            raise RuntimeError(
                f"WAV too small ({size} bytes){hint} — rtl_fm: {rtl_err[:300]!r}"
            )
        log.debug("[NOAA] WAV recorded: %.1f KB", size / 1024)

    # ------------------------------------------------------------------
    @staticmethod
    def _decode_apt_wav(wav_path: Path) -> Optional["Image.Image"]:
        """
        Full two-stage APT demodulation:

        Stage 1 (done by rtl_fm -M am):
            RF AM carrier → audio amplitude  (the 2400 Hz subcarrier tone)

        Stage 2 (done here):
            2400 Hz tone → envelope → pixel row brightness

        The wave pattern in the output image means Stage 2 was skipped
        and we were reading the raw 2400 Hz sine wave as pixel values.
        """
        if not HAS_PIL or not HAS_SCIPY:
            log.warning("[NOAA] Need Pillow + scipy for APT decode")
            return None

        # ── Load WAV ──────────────────────────────────────────────────
        with wave.open(str(wav_path), "rb") as wf:
            n_frames = wf.getnframes()
            framerate = wf.getframerate()
            raw = wf.readframes(n_frames)

        if not raw or n_frames == 0:
            log.warning("[NOAA] Empty WAV")
            return None

        samples = np.frombuffer(raw, dtype=np.int16).astype(np.float64)
        samples /= 32768.0
        log.debug(
            "[NOAA] Loaded %d samples @ %d Hz (%.1f s)",
            len(samples),
            framerate,
            len(samples) / framerate,
        )

        # ── Stage 2: isolate the 2400 Hz APT subcarrier ───────────────
        # Bandpass filter tightly around 2400 Hz.
        # The APT subcarrier occupies roughly 2400 ± 1040 Hz.
        low_hz = 500  # well below the subcarrier lower sideband
        high_hz = 4200  # well above the subcarrier upper sideband
        nyq = framerate / 2.0
        sos = sp_signal.butter(
            8,
            [low_hz / nyq, high_hz / nyq],
            btype="bandpass",
            output="sos",
        )
        filtered = sp_signal.sosfiltfilt(sos, samples)

        # ── Stage 2: envelope detection via Hilbert transform ─────────
        # This recovers the actual pixel brightness from the AM subcarrier.
        analytic = sp_signal.hilbert(filtered)
        envelope = np.abs(analytic)

        # ── Smooth to remove residual carrier ripple ──────────────────
        # Low-pass at 2× pixel Nyquist  (2080 px/line × 2 lines/s = 4160 Hz)
        lp_cutoff = 4160.0 / nyq
        if lp_cutoff < 1.0:
            sos_lp = sp_signal.butter(4, lp_cutoff, btype="low", output="sos")
            envelope = sp_signal.sosfiltfilt(sos_lp, envelope)

        # ── Resample to exact pixel rate: 4160 Sa/s ───────────────────
        pixel_rate = NOAADecoder.PIXELS_PER_LINE * NOAADecoder.LINE_RATE
        # Use scipy resample_poly for accurate rational resampling
        # (avoids the aliasing from naive integer decimation)
        from math import gcd

        g = gcd(framerate, pixel_rate)
        up = pixel_rate // g
        down = framerate // g
        resampled = sp_signal.resample_poly(envelope, up, down)

        # ── Reshape into image lines ───────────────────────────────────
        n_lines = len(resampled) // NOAADecoder.PIXELS_PER_LINE
        if n_lines < 10:
            log.warning("[NOAA] Only %d lines – pass too short or no signal", n_lines)
            return None

        matrix = resampled[: n_lines * NOAADecoder.PIXELS_PER_LINE]
        matrix = matrix.reshape(n_lines, NOAADecoder.PIXELS_PER_LINE)

        # ── Normalise to 0–255 ────────────────────────────────────────
        lo, hi = np.percentile(matrix, [1, 99])
        span = hi - lo
        if span < 1e-9:
            log.warning("[NOAA] No contrast – likely noise only")
            return None
        matrix = np.clip((matrix - lo) / span, 0.0, 1.0)
        matrix = (matrix * 255).astype(np.uint8)

        # ── Crop to Channel A + Channel B ─────────────────────────────
        # APT frame (2080 px):
        #   [0:39]    sync A
        #   [39:86]   space A
        #   [86:995]  channel A image  (909 px)
        #   [995:1040] telemetry A
        #   [1040:1079] sync B
        #   [1079:1126] space B
        #   [1126:2035] channel B image (909 px)
        #   [2035:2080] telemetry B
        img_a = matrix[:, 86:995]
        img_b = matrix[:, 1126:2035]
        composite = np.hstack([img_a, img_b])

        log.info("[NOAA] Decoded %d lines, image size %s", n_lines, composite.shape)
        return Image.fromarray(composite, mode="L")


# ──────────────────────────────────────────────────────────────────────────────
# SSTV Decoder
# ──────────────────────────────────────────────────────────────────────────────


class SSTVDecoder:
    """
    Listen for SSTV in 120-second slices via multimon-ng.
    Submits itself to the scheduler at Priority.SSTV and re-queues after
    each slice.
    """

    SLICE_SECONDS = 120

    def __init__(self, name: str, freq_hz: int):
        self.name = name
        self.freq_hz = freq_hz
        self._stop = threading.Event()

    def start(self):
        self._stop.clear()
        self._enqueue()
        log.info("[SSTV] Decoder started: %s @ %.3f MHz", self.name, self.freq_hz / 1e6)

    def stop(self):
        self._stop.set()

    def _enqueue(self):
        if self._stop.is_set():
            return
        task = SDRTask(Priority.SSTV, self._run_slice, name=f"SSTV-{self.name}")
        scheduler.submit(task)

    def _run_slice(self):
        if self._stop.is_set():
            return
        img_prefix = str(OUTPUT_DIR / f"sstv_{self.name}_{timestamp_str()}")
        log.debug("[SSTV] Slice: %s (%ds)", self.name, self.SLICE_SECONDS)

        cmd_fm = ["timeout", str(self.SLICE_SECONDS)] + rtl_fm_cmd(
            self.freq_hz, sample_rate=256_000, audio_rate=AUDIO_RATE, modulation="fm"
        )
        cmd_sox = sox_to_wav_cmd(AUDIO_RATE)
        cmd_mm = [
            "multimon-ng",
            "-t",
            "wav",
            "-a",
            "SSTV",
            "--timestamp",
            f"--sstv-image-path={img_prefix}",
            "-",
        ]

        p1 = subprocess.Popen(cmd_fm, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        p2 = subprocess.Popen(
            cmd_sox, stdin=p1.stdout, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
        )
        p3 = subprocess.Popen(
            cmd_mm, stdin=p2.stdout, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
        )
        p1.stdout.close()
        p2.stdout.close()

        try:
            for raw in p3.stdout:
                line = raw.decode(errors="replace").strip()
                if line:
                    log.info("[SSTV] %s", line)
                if self._stop.is_set():
                    break
        except Exception as exc:
            log.warning("[SSTV] %s: %s", self.name, exc)
        finally:
            kill_procs(p1, p2, p3)
            self._enqueue()


# ──────────────────────────────────────────────────────────────────────────────
# Spectrum Scanner
# ──────────────────────────────────────────────────────────────────────────────


class SpectrumScanner:
    """
    Sweep a frequency range opportunistically (Priority.SCANNER).
    Only runs when no higher-priority task is queued.
    Scanner tasks are skipped silently if the queue already has work.
    """

    def __init__(
        self,
        freq_start: int = 136_000_000,
        freq_end: int = 146_000_000,
        step: int = 500_000,
    ):
        self.freq_start = freq_start
        self.freq_end = freq_end
        self.step = step
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self):
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._submit_loop, daemon=True, name="scanner-submit"
        )
        self._thread.start()
        log.info(
            "[Scanner] %.0f–%.0f MHz, step %.0f kHz",
            self.freq_start / 1e6,
            self.freq_end / 1e6,
            self.step / 1e3,
        )

    def stop(self):
        self._stop.set()

    def _submit_loop(self):
        """
        Submit one sweep per iteration.  If higher-priority tasks are
        already queued, skip this round and wait before retrying —
        this avoids piling up scanner tasks in the queue.
        """
        freqs = list(range(self.freq_start, self.freq_end + 1, self.step))
        while not self._stop.is_set():
            # Only add a scan task when the queue is empty or only has
            # other scanner tasks waiting — don't pile up scans behind NOAA
            depth = scheduler.queue_depth()
            if depth > 2:
                log.debug("[Scanner] Queue depth %d – skipping scan round", depth)
                self._stop.wait(timeout=30)
                continue

            task = SDRTask(
                Priority.SCANNER,
                lambda f=freqs: self._run_sweep(f),
                name="Scanner-sweep",
            )
            scheduler.submit(task)
            # Wait for sweep to finish before submitting the next one
            task.wait(timeout=120)
            self._stop.wait(timeout=5)

    def _run_sweep(self, freqs: list):
        for freq in freqs:
            if self._stop.is_set():
                break
            power = self._measure_power(freq)
            log.debug("[Scanner] %.3f MHz  %.1f dB", freq / 1e6, power)
            if power > -30.0:
                log.info("[Scanner] *** Signal @ %.3f MHz  %.1f dB", freq / 1e6, power)
                self._record_burst(freq)

    @staticmethod
    def _measure_power(freq_hz: int) -> float:
        cmd = [
            "rtl_power",
            "-f",
            f"{freq_hz - 100_000}:{freq_hz + 100_000}:10000",
            "-g",
            "40",
            "-1",
            "-",
        ]
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=6)
            lines = r.stdout.decode(errors="replace").strip().splitlines()
            if not lines:
                return -100.0
            parts = lines[-1].split(",")
            vals = [float(x) for x in parts[6:]] if len(parts) > 6 else []
            return float(np.max(vals)) if vals else -100.0
        except Exception:
            return -100.0

    @staticmethod
    def _record_burst(freq_hz: int, duration: float = 3.0):
        out = OUTPUT_DIR.parent / f"burst_{freq_hz // 1000}kHz_{timestamp_str()}.wav"
        p1 = subprocess.Popen(
            [
                "timeout",
                str(duration),
                "rtl_fm",
                "-d",
                "0",
                "-f",
                str(freq_hz),
                "-M",
                "fm",
                "-s",
                "250000",
                "-r",
                "48000",
                "-g",
                "40",
                "-",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        p2 = subprocess.Popen(
            [
                "sox",
                "-t",
                "raw",
                "-r",
                "48000",
                "-e",
                "signed-integer",
                "-b",
                "16",
                "-c",
                "1",
                "-",
                str(out),
            ],
            stdin=p1.stdout,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        p1.stdout.close()
        p2.wait()
        p1.wait()
        log.info("[Scanner] Burst → %s", out)


# ──────────────────────────────────────────────────────────────────────────────
# Pure-Python Bell 202 / AX.25 soft-decoder  (offline / no external deps)
# ──────────────────────────────────────────────────────────────────────────────


class APRSSoftDecoder:
    SAMPLE_RATE = 48_000
    BAUD = 1200
    MARK = 1200.0
    SPACE = 2200.0

    def __init__(self, callback: Optional[Callable] = None):
        self._sr = self.SAMPLE_RATE
        self._spb = self._sr / self.BAUD
        self._callback = callback or (lambda p: log.info("[SoftAPRS] %s", p))
        self._buf = np.array([], dtype=np.float32)
        self._bits: list[int] = []
        if HAS_SCIPY:
            self._filt_m = sp_signal.butter(
                4,
                [self.MARK - 200, self.MARK + 200],
                btype="bandpass",
                fs=self._sr,
                output="sos",
            )
            self._filt_s = sp_signal.butter(
                4,
                [self.SPACE - 200, self.SPACE + 200],
                btype="bandpass",
                fs=self._sr,
                output="sos",
            )

    def feed(self, samples: np.ndarray):
        if not HAS_SCIPY:
            return
        self._buf = np.concatenate([self._buf, samples.astype(np.float32) / 32768.0])
        chunk = int(self._sr * 0.5)
        while len(self._buf) >= chunk:
            self._process_chunk(self._buf[:chunk])
            self._buf = self._buf[chunk:]

    def _process_chunk(self, chunk: np.ndarray):
        m = np.abs(sp_signal.sosfilt(self._filt_m, chunk))
        s = np.abs(sp_signal.sosfilt(self._filt_s, chunk))
        disc = (m > s).astype(np.int8)
        spb = int(self._spb)
        self._bits.extend(
            int(np.median(disc[i : i + spb])) for i in range(0, len(disc) - spb, spb)
        )
        self._try_decode()

    def _try_decode(self):
        FLAG = [0, 1, 1, 1, 1, 1, 1, 0]
        bits = self._bits
        i = 0
        while i < len(bits) - 8:
            if bits[i : i + 8] == FLAG:
                end = i + 8
                while end < min(i + 1200, len(bits) - 8):
                    if bits[end : end + 8] == FLAG:
                        self._decode_frame(bits[i + 8 : end])
                        bits = bits[end:]
                        i = 0
                        break
                    end += 1
                else:
                    i += 1
            else:
                i += 1
        self._bits = bits[-2400:]

    @staticmethod
    def _nrzi(bits):
        out, prev = [], 0
        for b in bits:
            out.append(0 if b != prev else 1)
            prev = b
        return out

    @staticmethod
    def _unstuff(bits):
        out, ones = [], 0
        for b in bits:
            if ones == 5:
                ones = 0
                continue
            out.append(b)
            ones = (ones + 1) if b else 0
        return out

    def _decode_frame(self, bits):
        try:
            bits = self._nrzi(self._unstuff(bits))
            while len(bits) % 8:
                bits.append(0)
            data = bytes(
                int("".join(map(str, bits[i : i + 8][::-1])), 2)
                for i in range(0, len(bits), 8)
            )
            if len(data) < 16:
                return
            pkt = self._parse_ax25(data)
            if pkt:
                self._callback(pkt)
        except Exception:
            pass

    @staticmethod
    def _parse_ax25(data: bytes) -> Optional[dict]:
        if len(data) < 16:
            return None

        def call(b):
            c = "".join(chr(x >> 1) for x in b[:6]).strip()
            s = (b[6] >> 1) & 0x0F
            return f"{c}-{s}" if s else c

        try:
            dst, src = call(data[0:7]), call(data[7:14])
            off = 14
            while off < len(data) and not (data[off - 1] & 1):
                off += 7
            off += 2
            return {
                "src": src,
                "dst": dst,
                "info": data[off:].decode("ascii", errors="replace"),
            }
        except Exception:
            return None


# ──────────────────────────────────────────────────────────────────────────────
# NOAA pass scheduler
# ──────────────────────────────────────────────────────────────────────────────


def schedule_noaa_passes(stop_event: threading.Event):
    """
    Round-robin NOAA pass submissions.
    Submits at Priority.NOAA — runs behind APRS, ahead of SSTV/Scanner.
    """

    def loop():
        while not stop_event.is_set():
            for name, freq in NOAA_FREQS_HZ.items():
                if stop_event.is_set():
                    break
                dec = NOAADecoder(name, freq)
                task = dec.submit_pass()
                # Wait for this pass to complete before queuing the next
                task.wait()
                stop_event.wait(timeout=60)

    t = threading.Thread(target=loop, daemon=True, name="noaa-sched")
    t.start()
    return t


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────


def main():
    log.info("=" * 60)
    log.info("RTL-SDR v4 Multi-Mode Image Scanner")
    log.info("Output → %s", OUTPUT_DIR)
    log.info("=" * 60)

    if not HAS_PIL:
        log.warning("Pillow not installed  →  pip install Pillow")
    if not HAS_SCIPY:
        log.warning("scipy not installed   →  pip install scipy")

    check_external_tools()

    stop_event = threading.Event()

    # Start the central scheduler first
    scheduler.start()

    # Register decoders — each self-submits tasks to the scheduler
    aprs = APRSDecoder(freq_hz=APRS_FREQ_HZ)
    aprs.start()

    sstv_decoders = [SSTVDecoder(n, f) for n, f in SSTV_FREQS_HZ.items()]
    for d in sstv_decoders:
        d.start()

    scanner = SpectrumScanner()
    scanner.start()

    schedule_noaa_passes(stop_event)

    def _sig(sig, _):
        log.info("Shutdown (signal %d)", sig)
        stop_event.set()

    signal.signal(signal.SIGINT, _sig)
    signal.signal(signal.SIGTERM, _sig)

    log.info("Running – Ctrl+C to stop")
    log.info("Priority order: APRS(30s slices) > NOAA(900s) > SSTV(120s) > Scanner")
    stop_event.wait()

    log.info("Stopping…")
    aprs.stop()
    scanner.stop()
    for d in sstv_decoders:
        d.stop()
    scheduler.stop()
    log.info("Done. Images in %s", OUTPUT_DIR)


if __name__ == "__main__":
    main()
