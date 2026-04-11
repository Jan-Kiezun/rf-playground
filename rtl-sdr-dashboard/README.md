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

## License

MIT
