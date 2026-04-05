#!/usr/bin/env python3
"""
APRS Decoder for 144.800 MHz — RTL-FM | SOX | Direwolf
=======================================================
Pipeline:
  rtl_fm (raw S16LE PCM) → sox (convert to WAV stream) → direwolf stdin

Direwolf 1.6 accepts WAV-formatted stdin when launched as:
  direwolf -r 24000 -n 1 -b 16 -

Requirements:
    sudo apt install rtl-sdr direwolf sox
    pip install aprslib
"""

import argparse
import atexit
import datetime
import json
import os
import socket
import struct
import subprocess
import sys
import threading
import time

try:
    import aprslib
    from aprslib.parsing import parse as aprs_parse

    HAS_APRSLIB = True
except ImportError:
    HAS_APRSLIB = False
    print("[WARN] aprslib not installed — run: pip install aprslib\n")

# ─── Config ───────────────────────────────────────────────────────────────────

APRS_FREQ = "144.8M"
AUDIO_RATE = 24000
AGWPE_HOST = "127.0.0.1"
AGWPE_PORT = 8000
GAIN = "42"

# ─── Colors ───────────────────────────────────────────────────────────────────


class C:
    RESET = "\033[0m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    BOLD = "\033[1m"
    DIM = "\033[2m"


def ts():
    return datetime.datetime.now().strftime("%H:%M:%S")


def info(m):
    print(f"{C.BLUE}[{ts()}] {m}{C.RESET}")


def warn(m):
    print(f"{C.YELLOW}[WARN] {m}{C.RESET}")


def err(m):
    print(f"{C.RED}[ERR]  {m}{C.RESET}")


def ok(m):
    print(f"{C.GREEN}[OK]   {m}{C.RESET}")


# ─── Dependency check ─────────────────────────────────────────────────────────


def check_deps():
    missing = [
        t
        for t in ("rtl_fm", "direwolf", "sox")
        if not any(
            os.access(os.path.join(d, t), os.X_OK)
            for d in os.environ.get("PATH", "").split(":")
        )
    ]
    if missing:
        err(f"Missing required tools: {', '.join(missing)}")
        print("  sudo apt install rtl-sdr direwolf sox")
        sys.exit(1)


# ─── AGWPE client ─────────────────────────────────────────────────────────────


class AGWPEClient:
    HDR = 36

    def __init__(self, host, port, on_frame):
        self.host = host
        self.port = port
        self.on_frame = on_frame
        self.running = False
        self._sock = None

    def _recvall(self, n):
        buf = b""
        while len(buf) < n:
            c = self._sock.recv(n - len(buf))
            if not c:
                raise ConnectionResetError("Direwolf closed connection")
            buf += c
        return buf

    def _register(self):
        hdr = struct.pack("<BBBBBBBBI", 0, 0, 0, 0, ord("R"), 0, 0, 0, 0)
        hdr += b"\x00" * (self.HDR - len(hdr))
        self._sock.sendall(hdr)

    def connect(self, retries=30, delay=0.5):
        for i in range(retries):
            try:
                self._sock = socket.create_connection((self.host, self.port), timeout=3)
                self._sock.settimeout(None)
                self._register()
                ok(f"Connected to Direwolf AGWPE on {self.host}:{self.port}")
                return
            except (ConnectionRefusedError, OSError):
                print(
                    f"\r  {C.DIM}Waiting for Direwolf{'.' * (i % 4 + 1):<5}{C.RESET}",
                    end="",
                    flush=True,
                )
                time.sleep(delay)
        print()
        raise RuntimeError(
            f"Could not connect to Direwolf AGWPE after {retries} attempts.\n"
            f"Re-run with --verbose to see full direwolf output."
        )

    def run(self):
        self.running = True
        try:
            while self.running:
                hdr = self._recvall(self.HDR)
                kind = chr(hdr[4])
                call = hdr[8:18].rstrip(b"\x00").decode("ascii", errors="replace")
                dlen = struct.unpack_from("<I", hdr, 28)[0]
                data = self._recvall(dlen) if dlen else b""
                if kind == "U":
                    self.on_frame(call, data)
        except (ConnectionResetError, OSError) as e:
            if self.running:
                err(f"AGWPE: {e}")
        finally:
            self.running = False

    def close(self):
        self.running = False
        if self._sock:
            try:
                self._sock.close()
            except:
                pass


# ─── APRS display ─────────────────────────────────────────────────────────────


def parse_aprs(raw: bytes) -> dict:
    result = {"raw": raw}
    if HAS_APRSLIB:
        try:
            result.update(aprs_parse(raw.decode("latin-1", errors="replace")))
            return result
        except Exception as e:
            result["parse_error"] = str(e)
    result["text"] = raw.decode("latin-1", errors="replace")
    return result


def display_packet(callsign: str, aprs: dict, count: int):
    sep = "─" * 64
    print(f"\n{C.CYAN}{sep}{C.RESET}")
    print(f"{C.BOLD}{C.GREEN}[{ts()}] Packet #{count}{C.RESET}")

    src = aprs.get("from", callsign)
    dst = aprs.get("to", "?")
    path = aprs.get("path", "")
    print(
        f"  {C.BOLD}From :{C.RESET} {C.YELLOW}{src}{C.RESET}  →  {dst}"
        + (f"  {C.DIM}via {path}{C.RESET}" if path else "")
    )

    fmt = aprs.get("format") or aprs.get("type") or "unknown"
    print(f"  {C.BOLD}Type :{C.RESET} {fmt}")

    lat = aprs.get("latitude")
    lon = aprs.get("longitude")
    if lat is not None and lon is not None:
        lat_f, lon_f = float(lat), float(lon)
        print(
            f"  {C.BOLD}Pos  :{C.RESET} {C.CYAN}{lat_f:.6f}°N  {lon_f:.6f}°E{C.RESET}"
        )
        print(
            f"  {C.BLUE}Map  :{C.RESET} https://www.openstreetmap.org/"
            f"?mlat={lat_f}&mlon={lon_f}#map=13/{lat_f}/{lon_f}"
        )

    for label, key, unit in [
        ("Speed", "speed", "km/h"),
        ("Course", "course", "°"),
        ("Alt", "altitude", "m"),
        ("Temp", "temperature", "°C"),
        ("Humidity", "humidity", "%"),
        ("Pressure", "pressure", "hPa"),
        ("Wind spd", "wind_speed", "km/h"),
        ("Wind dir", "wind_direction", "°"),
        ("Rain 1h", "rain_1h", "mm"),
    ]:
        val = aprs.get(key)
        if val is not None:
            print(f"  {C.BOLD}{label + ':':{12}}{C.RESET} {val} {unit}")

    for field in ("comment", "status", "message", "text"):
        val = aprs.get(field)
        if val and str(val).strip():
            print(f"  {C.BOLD}{'Info:':{12}}{C.RESET} {str(val).strip()[:120]}")
            break

    raw = aprs.get("raw", b"")
    raw_str = (
        raw.decode("latin-1", errors="replace") if isinstance(raw, bytes) else str(raw)
    )
    print(f"  {C.DIM}Raw  : {raw_str[:80]}{'…' if len(raw_str) > 80 else ''}{C.RESET}")
    print(f"{C.CYAN}{sep}{C.RESET}")


# ─── Main decoder ─────────────────────────────────────────────────────────────


class APRSDecoder:
    def __init__(self, freq, gain, ppm, log_file, verbose):
        self.freq = freq
        self.gain = gain
        self.ppm = ppm
        self.log_file = log_file
        self.verbose = verbose
        self.count = 0
        self._procs: list[subprocess.Popen] = []

    def _cleanup(self):
        for p in self._procs:
            try:
                p.terminate()
                p.wait(timeout=3)
            except Exception:
                try:
                    p.kill()
                except:
                    pass

    def _fwd(self, stream, label: str, always: bool = False):
        """Forward lines from a subprocess stream to stdout."""
        try:
            for raw_line in stream:
                line = raw_line.decode("utf-8", errors="replace").rstrip()
                if always or self.verbose:
                    print(f"  {C.DIM}[{label}] {line}{C.RESET}")
        except Exception:
            pass

    def _on_frame(self, callsign: str, data: bytes):
        aprs = parse_aprs(data)
        self.count += 1
        display_packet(callsign, aprs, self.count)
        if self.log_file:
            try:
                with open(self.log_file, "a") as f:
                    rec = {
                        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
                        "src": callsign,
                        **{
                            k: v
                            for k, v in aprs.items()
                            if k != "raw" and not isinstance(v, bytes)
                        },
                        "raw": aprs.get("raw", b"").decode("latin-1", errors="replace"),
                    }
                    f.write(json.dumps(rec) + "\n")
            except Exception as e:
                warn(f"Log write failed: {e}")

    def run(self):
        check_deps()
        atexit.register(self._cleanup)

        print(f"\n{C.BOLD}{C.BLUE}{'═' * 56}{C.RESET}")
        print(
            f"{C.BOLD}{C.BLUE}  APRS Decoder — {self.freq}  "
            f"(rtl_fm | sox | direwolf){C.RESET}"
        )
        print(f"{C.BOLD}{C.BLUE}{'═' * 56}{C.RESET}")
        print(
            f"  Gain: {self.gain or 'auto'} dB  |  "
            f"PPM: {self.ppm}  |  Log: {self.log_file or 'off'}"
        )
        print(f"  {C.YELLOW}Press Ctrl+C to stop.{C.RESET}\n")

        # ── rtl_fm ────────────────────────────────────────────────────────────
        # Outputs raw S16LE mono PCM at AUDIO_RATE to stdout
        rtlfm_cmd = [
            "rtl_fm",
            "-f",
            self.freq,
            "-M",
            "fm",
            "-s",
            str(AUDIO_RATE),
            "-E",
            "dc",
            "-E",
            "deemp",  # de-emphasis — essential for APRS
            "-",  # raw PCM to stdout
        ]
        if self.gain:
            rtlfm_cmd += ["-g", self.gain]
        if self.ppm:
            rtlfm_cmd += ["-p", str(self.ppm)]

        # ── sox ─────────────────────────────���─────────────────────────────────
        # Wraps the raw S16LE stream in a WAV header so direwolf can read it.
        # Input:  raw signed 16-bit little-endian, 1ch, AUDIO_RATE
        # Output: WAV on stdout
        sox_cmd = [
            "sox",
            "-t",
            "raw",  # input type: raw PCM
            "-e",
            "signed",  # signed integers
            "-b",
            "16",  # 16-bit
            "-r",
            str(AUDIO_RATE),
            "-c",
            "1",  # mono
            "-",  # read from stdin
            "-t",
            "wav",  # output type: WAV
            "-r",
            str(AUDIO_RATE),
            "-",  # write to stdout
        ]

        # ── direwolf ──────────────────────────────────────────────────────────
        # Reads WAV from stdin, decodes APRS, serves frames via AGWPE TCP
        dw_cmd = [
            "direwolf",
            "-r",
            str(AUDIO_RATE),
            "-D",
            "1",  # decode-only
            "-t",
            "0",  # no ANSI colour (we do our own)
            "-",  # read audio from stdin (WAV format)
        ]

        info(f"rtl_fm  : {' '.join(rtlfm_cmd)}")
        info(f"sox     : {' '.join(sox_cmd)}")
        info(f"direwolf: {' '.join(dw_cmd)}")
        print()

        # ── launch pipeline: rtl_fm | sox | direwolf ──────────────────────────
        rtlfm_proc = subprocess.Popen(
            rtlfm_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self._procs.append(rtlfm_proc)

        sox_proc = subprocess.Popen(
            sox_cmd,
            stdin=rtlfm_proc.stdout,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self._procs.append(sox_proc)
        rtlfm_proc.stdout.close()

        dw_proc = subprocess.Popen(
            dw_cmd,
            stdin=sox_proc.stdout,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,  # merge so we see everything
        )
        self._procs.append(dw_proc)
        sox_proc.stdout.close()

        # Forward stderr from rtl_fm and sox (always show errors)
        for proc, label in [(rtlfm_proc, "rtl_fm"), (sox_proc, "sox")]:
            threading.Thread(
                target=self._fwd, args=(proc.stderr, label, True), daemon=True
            ).start()

        # Forward direwolf stdout (verbose = always show, else only on error)
        threading.Thread(
            target=self._fwd,
            args=(dw_proc.stdout, "direwolf", self.verbose),
            daemon=True,
        ).start()

        # ── connect AGWPE ─────────────────────────────────────────────────────
        time.sleep(2.5)
        agwpe = AGWPEClient(AGWPE_HOST, AGWPE_PORT, self._on_frame)
        try:
            agwpe.connect()
        except RuntimeError as e:
            err(str(e))
            self._cleanup()
            sys.exit(1)

        agwpe_t = threading.Thread(target=agwpe.run, daemon=True)
        agwpe_t.start()

        print(f"\n{C.GREEN}  ✔ Listening on {self.freq}…{C.RESET}\n")

        # ── status loop ───────────────────────────────────────────────────────
        try:
            while all(p.poll() is None for p in self._procs):
                print(
                    f"\r{C.DIM}[{ts()}]  Packets decoded: {self.count}   {C.RESET}",
                    end="",
                    flush=True,
                )
                time.sleep(5)

            for p, name in zip(self._procs, ["rtl_fm", "sox", "direwolf"]):
                rc = p.poll()
                if rc is not None:
                    err(f"{name} exited unexpectedly (code {rc})")

        except KeyboardInterrupt:
            print(f"\n\n{C.YELLOW}Stopped by user.{C.RESET}")
        finally:
            agwpe.close()
            self._cleanup()
            print(f"\n{C.GREEN}Total packets decoded: {self.count}{C.RESET}")
            if self.log_file:
                print(f"{C.GREEN}Log: {self.log_file}{C.RESET}")


# ─── Entry point ──────────────────────────────────────────────────────────────


def main():
    p = argparse.ArgumentParser(
        description="APRS decoder — 144.800 MHz via rtl_fm | sox | direwolf"
    )
    p.add_argument(
        "-f", "--freq", default=APRS_FREQ, help="Frequency (default: 144.8M)"
    )
    p.add_argument(
        "-g", "--gain", default=GAIN, help="Tuner gain dB or '' for auto (default: 42)"
    )
    p.add_argument(
        "-p", "--ppm", type=int, default=0, help="Frequency correction PPM (default: 0)"
    )
    p.add_argument("-l", "--log", default=None, help="JSONL log file path")
    p.add_argument(
        "-v", "--verbose", action="store_true", help="Show all subprocess output"
    )
    args = p.parse_args()

    APRSDecoder(
        freq=args.freq,
        gain=args.gain,
        ppm=args.ppm,
        log_file=args.log,
        verbose=args.verbose,
    ).run()


if __name__ == "__main__":
    main()
