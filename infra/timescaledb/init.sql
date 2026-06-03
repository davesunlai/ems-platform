-- Schéma časové databáze pro telemetrii.
CREATE TABLE IF NOT EXISTS samples (
    time       TIMESTAMPTZ      NOT NULL,
    device_id  TEXT             NOT NULL,
    metric     TEXT             NOT NULL,
    value      DOUBLE PRECISION NOT NULL,
    unit       TEXT             NOT NULL,
    quality    TEXT             NOT NULL DEFAULT 'good'
);

-- Hypertable particionovaná podle času (TimescaleDB).
SELECT create_hypertable('samples', 'time', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_samples_dev_metric_time
    ON samples (device_id, metric, time DESC);
