# 🛰️ RTL-SDR v4 Dashboard

A browser-based dashboard for managing and visualizing data from an RTL-SDR v4 USB dongle. Features FM radio streaming, weather sensor decoding, ADS-B aircraft tracking, NOAA satellite imagery, and more.

## Architecture

```
Browser (React 18 + TypeScript)
    ↕ HTTP + WebSocket
FastAPI Backend (Python 3.12)
    ├── Celery + Redis (task queue)
    ├── PostgreSQL + TimescaleDB (time-series data)
    └── RTL-SDR Tools container (privileged, USB access)
```

## Features

- **Dashboard** — Live signal feed, device status, mini charts
- **Connections** — Per-protocol connector cards with toggle, config, and manual pull
- **Radio Player** — FM radio via HLS stream with RDS metadata display
- **Scheduler** — Cron-based recurring jobs via Celery Beat

## Supported Protocols

| Connector | Tool | Output |
|---|---|---|
| FM Radio | `rtl_fm` + `multimon-ng` | RDS station/artist/song |
| Weather Sensors | `rtl_433` | Temperature, humidity, pressure |
| Aircraft Tracking | `dump1090` | ADS-B position, callsign, altitude |
| NOAA Weather Satellite | `rtl_fm` + `noaa-apt` | Decoded satellite images |

## Prerequisites

### Host System Setup

1. **Blacklist conflicting kernel module** (required for USB passthrough):
   ```bash
   echo "blacklist dvb_usb_rtl28xxu" | sudo tee /etc/modprobe.d/rtlsdr.conf
   sudo modprobe -r dvb_usb_rtl28xxu 2>/dev/null || true
   ```

2. **Install Docker & Docker Compose**:
   ```bash
   # Docker Engine + Compose plugin
   curl -fsSL https://get.docker.com | sh
   ```

3. **Verify RTL-SDR device is detected**:
   ```bash
   lsusb | grep -i rtl
   # Should show: Bus ... ID 0bda:2838 Realtek Semiconductor Corp. RTL2838 DVB-T
   ```

## Quick Start

```bash
# 1. Clone and enter the dashboard directory
cd rtl-sdr-dashboard

# 2. Copy environment file and configure
cp .env.example .env
# Edit .env if needed (database passwords, API keys, etc.)

# 3. Start all services
docker compose up -d

# 4. Open the dashboard
open http://localhost
```

## Configuration

Edit `.env` before starting:

```env
# Required
POSTGRES_PASSWORD=your_secure_password
DATABASE_URL=postgresql+asyncpg://sdr:your_secure_password@postgres:5432/sdrdb

# Optional — for radio metadata (album art, artist info)
LASTFM_API_KEY=your_lastfm_api_key
```

## Services

| Service | Port | Description |
|---|---|---|
| Nginx | 80 | Reverse proxy + HLS serving |
| Frontend | 3000 (internal) | React dashboard |
| Backend | 8000 (internal) | FastAPI REST + WebSocket |
| Worker | — | Celery task worker + Beat scheduler |
| SDR Tools | 1234 | `rtl_tcp` multiplexer daemon |
| Redis | 6379 (internal) | Task broker + pub/sub |
| PostgreSQL | 5432 (internal) | TimescaleDB time-series DB |

## API Overview

```
GET  /api/health                    → Health check
GET  /api/device/status             → RTL-SDR device info
GET  /api/connectors                → List connectors
POST /api/connectors/{id}/toggle    → Enable/disable connector
PUT  /api/connectors/{id}/config    → Update frequency, gain, etc.
POST /api/connectors/{id}/pull      → Trigger manual data pull
GET  /api/data/{connector_id}       → Paginated signal history
GET  /api/data/latest               → Latest entry per connector
GET  /api/images                    → List NOAA satellite images
GET  /api/schedule                  → List scheduled jobs
POST /api/schedule                  → Create scheduled job
WS   /ws/live                       → Real-time event stream
GET  /stream/radio.m3u8             → HLS FM radio playlist
```

## Development

Run the backend locally:

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Run the frontend locally:

```bash
cd frontend
npm install
npm run dev
```

## Important Notes

- **Only one process can own the RTL-SDR dongle at a time.** The `sdr-tools` container runs `rtl_tcp` as a multiplexer, allowing multiple workers to connect as virtual devices.
- **HLS audio latency** is ~5–15 seconds by design. For lower latency, consider WebSocket PCM streaming.
- **NOAA satellite passes** last ~15 minutes — schedule accordingly (every 90–120 min for continuous coverage).
- **USB passthrough** requires the `sdr-tools` container to be `privileged`. This is a Docker Compose requirement for USB device access.

## Troubleshooting

**Device not found:**
```bash
# Check if module is blacklisted
lsmod | grep dvb_usb
# Check USB device
lsusb | grep Realtek
# Run rtl_test in the sdr-tools container
docker compose exec sdr-tools rtl_test -t
```

**No data from connectors:**
- Ensure the connector is enabled (toggle in Connections page)
- Use "Pull Now" to manually trigger a data collection
- Check Celery worker logs: `docker compose logs worker`

**Audio stream not working:**
- Ensure `rtl_fm` and `ffmpeg` are available in the `sdr-tools` container
- Start the stream from the Radio Player page
- HLS segments appear in `/tmp/hls/` after ~10 seconds

## Radio Reception Tests

The `tests/` directory contains a pytest suite that verifies FM broadcast
reception end-to-end — useful for diagnosing whether problems are in the
hardware/driver layer or in the application code.

### Device auto-detection

The tests automatically choose how to talk to the dongle:

1. **Direct device** (dongle plugged straight into the machine where you run
   the tests): the tests use the device index directly (default `0`).  No
   extra daemons required.
2. **Via `rtl_tcp`** (e.g. the Docker stack is running): if the tests can
   reach `rtl_tcp` at `RTL_TCP_HOST:RTL_TCP_PORT`, they use the network
   device string instead.

You do not need to set anything manually — just plug in the dongle and run.

### Stations tested

| Station | Frequency |
|---|---|
| Radio Gdańsk | 103.7 MHz |
| RMF FM | 98.4 MHz |
| Radio ZET | 105.0 MHz |
| Radio Maryja | 88.9 MHz |

### Prerequisites

Install the required tools on the **host machine** where you run the tests:

```bash
# Debian / Ubuntu
sudo apt-get install rtl-sdr sox ffmpeg multimon-ng python3-pip

# Arch Linux
sudo pacman -S rtl-sdr sox ffmpeg multimon-ng python-pip
```

Also blacklist the conflicting DVB kernel module so the dongle is not claimed
by the OS driver:

```bash
echo "blacklist dvb_usb_rtl28xxu" | sudo tee /etc/modprobe.d/rtlsdr.conf
sudo modprobe -r dvb_usb_rtl28xxu 2>/dev/null || true
```

### Running the tests

```bash
# 1. Install test dependencies
pip install -r tests/requirements-test.txt

# 2. Run all tests — device is auto-detected (dongle plugged in directly)
pytest tests/test_radio_reception.py -v

# 3. Run only the quick device-sanity checks first (no RF signal needed)
pytest tests/test_radio_reception.py -v -k "device"

# 4. Run only the per-station audio tests
pytest tests/test_radio_reception.py -v -k "station"

# 5. Run only the RDS decoding test
pytest tests/test_radio_reception.py -v -k "rds"

# 6. Run only the HLS pipeline test
pytest tests/test_radio_reception.py -v -k "hls"

# 7. Run via a remote rtl_tcp (e.g. Docker stack on another machine)
RTL_TCP_HOST=192.168.1.50 RTL_TCP_PORT=1234 pytest tests/test_radio_reception.py -v

# 8. Increase sample window (default is 15 s per station, minimum recommended)
FM_SAMPLE_DURATION=30 pytest tests/test_radio_reception.py -v
```

### Environment variables

| Variable | Default | Description |
|---|---|---|
| `RTL_SDR_DEVICE_INDEX` | `0` | Direct device index when `rtl_tcp` is not running |
| `RTL_TCP_HOST` | `localhost` | Host running `rtl_tcp` (used only if reachable) |
| `RTL_TCP_PORT` | `1234` | Port of `rtl_tcp` |
| `FM_SAMPLE_DURATION` | `15` | Seconds to sample per station |
| `HLS_OUTPUT_DIR` | `/tmp/hls_test` | Directory for HLS segment output |

### What each test checks

| Test | What it verifies |
|---|---|
| `test_device_detected` | `rtl_test -t` finds the dongle (no RF needed) |
| `test_device_can_sample` | Dongle produces IQ samples at 2 048 000 S/s (no RF needed) |
| `test_station_produces_audio[Radio Gdańsk]` | `rtl_fm` receives ≥ 8 KiB of PCM from 103.7 MHz |
| `test_station_produces_audio[RMF FM]` | `rtl_fm` receives ≥ 8 KiB of PCM from 98.4 MHz |
| `test_station_produces_audio[Radio ZET]` | `rtl_fm` receives ≥ 8 KiB of PCM from 105.0 MHz |
| `test_station_produces_audio[Radio Maryja]` | `rtl_fm` receives ≥ 8 KiB of PCM from 88.9 MHz |
| `test_rds_decoding_rmf_fm` | `multimon-ng` decodes at least one RDS frame from RMF FM |
| `test_hls_pipeline_creates_playlist` | `rtl_fm → sox → ffmpeg` pipeline writes `radio.m3u8` within 20 s |

### Interpreting failures

| Symptom | Likely cause |
|---|---|
| `test_device_detected` fails | Dongle not plugged in, or `dvb_usb_rtl28xxu` not blacklisted |
| `test_device_can_sample` fails | USB transfer issue — try a different USB port or cable |
| All station tests fail with 0 bytes received | Signal too weak, or wrong antenna — verify with `gqrx` first |
| Tests are skipped | The required binary (`rtl_fm`, `rtl_test`, `multimon-ng`, `sox`, `ffmpeg`) is not installed |
| Audio tests pass but RDS test fails | Signal strong enough for audio but too weak for RDS carrier sync |
| HLS test fails but audio tests pass | `sox` or `ffmpeg` not installed, or permission issue on HLS dir |

## License

MIT
