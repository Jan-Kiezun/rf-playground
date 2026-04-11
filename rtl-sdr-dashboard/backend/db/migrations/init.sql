-- Enable TimescaleDB extension
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- Connectors configuration
CREATE TABLE IF NOT EXISTS connectors (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL,
  protocol TEXT NOT NULL,
  enabled BOOLEAN DEFAULT FALSE,
  frequency_hz BIGINT,
  gain FLOAT,
  sample_rate INT,
  extra_config JSONB,
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Time-series signal data (hypertable)
CREATE TABLE IF NOT EXISTS signal_data (
  id UUID DEFAULT gen_random_uuid(),
  time TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  connector_id UUID REFERENCES connectors(id),
  data JSONB,
  raw_text TEXT
);
SELECT create_hypertable('signal_data', 'time', if_not_exists => TRUE);

-- Satellite images
CREATE TABLE IF NOT EXISTS sat_images (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  connector_id UUID REFERENCES connectors(id),
  captured_at TIMESTAMPTZ DEFAULT NOW(),
  file_path TEXT,
  pass_metadata JSONB
);

-- Scheduled jobs
CREATE TABLE IF NOT EXISTS scheduled_jobs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  connector_id UUID REFERENCES connectors(id),
  cron_expression TEXT,
  enabled BOOLEAN DEFAULT TRUE,
  last_run TIMESTAMPTZ,
  next_run TIMESTAMPTZ
);

-- Seed default connectors
INSERT INTO connectors (name, protocol, frequency_hz, sample_rate, extra_config)
VALUES
  ('FM Radio', 'fm', 98100000, 200000, '{"rds": true}'),
  ('Weather Sensors (433MHz)', 'rtl433', 433920000, 250000, '{}'),
  ('ADS-B Aircraft', 'adsb', 1090000000, 2000000, '{}'),
  ('NOAA Weather Sat', 'noaa', 137620000, 60000, '{"satellite": "NOAA-19"}')
ON CONFLICT DO NOTHING;
