-- Run with psql -X -v ON_ERROR_STOP=1 against edgex_db, outside a transaction.
-- Supports the existing per-device LATERAL query, including inactive sources.
-- INCLUDE(id) lets PostgreSQL return the event identity from the index instead
-- of estimating a cheap scan of the global origin index with a device filter.
-- CONCURRENTLY preserves sensor writes while the index is built.
SET lock_timeout = '5s';
SET statement_timeout = '10min';
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_event_device_info_origin_cover
    ON core_data.event (device_info_id, origin DESC) INCLUDE (id);
-- Verify indisvalid/indisready and EXPLAIN before declaring recovery.
-- Rollback, only if required:
-- DROP INDEX CONCURRENTLY core_data.idx_event_device_info_origin_cover;
