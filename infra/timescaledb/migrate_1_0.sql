-- TERA EMS v1.0.0 — komprese surových vzorků + 15min continuous aggregate.
-- Idempotentní; spouštět: docker exec -i infra-timescaledb-1 psql -U ems -d ems < infra/timescaledb/migrate_1_0.sql
-- TimescaleDB 2.27 (hypercore/columnstore API; starší názvy compress_* jsou aliasy).

-- 1) 15min agregát: avg/min/max/count per zařízení × metrika. Mřížka od epochy = 9:00:00–9:14:59,
--    stejná jako spotové sloty OTE. Realtime (materialized_only=false) = čerstvý okraj se dopočítá živě.
CREATE MATERIALIZED VIEW IF NOT EXISTS samples_15m
WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
SELECT time_bucket('15 minutes', time) AS bucket,
       device_id, metric,
       avg(value)  AS avg,
       min(value)  AS min,
       max(value)  AS max,
       count(*)    AS n
FROM samples
GROUP BY 1, 2, 3
WITH NO DATA;

CREATE INDEX IF NOT EXISTS samples_15m_dev_metric_bucket ON samples_15m (device_id, metric, bucket DESC);

-- refresh každých 15 min; okno zpět 14 dní kvůli datům dohraným z bufferu EMSBOXu po výpadku
SELECT add_continuous_aggregate_policy('samples_15m',
    start_offset => INTERVAL '14 days',
    end_offset   => INTERVAL '15 minutes',
    schedule_interval => INTERVAL '15 minutes',
    if_not_exists => TRUE);

-- 2) Komprese surových vzorků starších 14 dní (beze ztráty dat; inserty do komprimovaných chunků jsou povolené,
--    jen pomalejší — týká se jen bufferu dohrávaného po >14denním výpadku).
ALTER TABLE samples SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'device_id, metric',
    timescaledb.compress_orderby   = 'time DESC'
);
SELECT add_compression_policy('samples', INTERVAL '14 days', if_not_exists => TRUE);

-- 3) Retence surových vzorků: 3 měsíce (= vždy aktuální měsíc + 2 celé měsíce zpět; maže se po 7denních
--    chuncích, takže reálně zůstává 90–97 dní). Rozhodnutí 23. 10. 2026: forenzní detail starší než 2 celé
--    měsíce není potřeba. 15min agregát samples_15m se NEMAŽE (účtování, statistiky). Agregát je k datu
--    mazání dávno zmaterializovaný (refresh okno 14 dní + jednorázový dopočet níže).
SELECT add_retention_policy('samples', INTERVAL '3 months', if_not_exists => TRUE);

-- 4) Jednorázové dopočítání historie agregátu (5 měsíců ≈ minuty). Komprese starých chunků proběhne
--    na pozadí politikou (první průchod může trvat desítky minut; sleduj timescaledb_information.jobs).
CALL refresh_continuous_aggregate('samples_15m', '2026-05-01 00:00:00+00', now() - INTERVAL '15 minutes');

SELECT 'samples_15m rows' AS co, count(*) FROM samples_15m;
