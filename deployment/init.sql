-- SBITB PostgreSQL schema — audit trail, trade records, market data
-- Retention: 7 years (SEBI requirement)

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- Audit trail table (append-only, hash-chained)
CREATE TABLE IF NOT EXISTS audit_trail (
    id            BIGSERIAL PRIMARY KEY,
    timestamp     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    event_type    VARCHAR(50) NOT NULL,
    data          JSONB NOT NULL DEFAULT '{}',
    strategy_id   VARCHAR(50) NOT NULL DEFAULT '',
    order_id      VARCHAR(50) NOT NULL DEFAULT '',
    prev_checksum VARCHAR(64) NOT NULL,
    checksum      VARCHAR(64) NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Prevent deletion and updates (append-only)
REVOKE UPDATE, DELETE ON audit_trail FROM PUBLIC;

-- Trade records
CREATE TABLE IF NOT EXISTS trades (
    id              BIGSERIAL PRIMARY KEY,
    order_id        VARCHAR(50) NOT NULL,
    symbol          VARCHAR(50) NOT NULL,
    segment         VARCHAR(10) NOT NULL,
    side            VARCHAR(4) NOT NULL,
    quantity        INTEGER NOT NULL,
    price           NUMERIC(20, 4) NOT NULL,
    strategy_id     VARCHAR(50) NOT NULL,
    tag             VARCHAR(20) NOT NULL DEFAULT '',
    trade_timestamp TIMESTAMPTZ NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades (symbol);
CREATE INDEX IF NOT EXISTS idx_trades_strategy ON trades (strategy_id);
CREATE INDEX IF NOT EXISTS idx_trades_timestamp ON trades (trade_timestamp);

-- Kill switch events
CREATE TABLE IF NOT EXISTS kill_switch_events (
    id              BIGSERIAL PRIMARY KEY,
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    level           VARCHAR(10) NOT NULL,
    path            VARCHAR(10) NOT NULL,
    reason          TEXT NOT NULL DEFAULT '',
    order_count     INTEGER NOT NULL DEFAULT 0
);

-- Daily risk state snapshots
CREATE TABLE IF NOT EXISTS risk_snapshots (
    id                  BIGSERIAL PRIMARY KEY,
    snapshot_date       DATE NOT NULL,
    daily_order_count   INTEGER NOT NULL DEFAULT 0,
    current_exposure    NUMERIC(20, 4) NOT NULL DEFAULT 0,
    margin_available    NUMERIC(20, 4) NOT NULL DEFAULT 0,
    margin_used         NUMERIC(20, 4) NOT NULL DEFAULT 0,
    daily_pnl           NUMERIC(20, 4) NOT NULL DEFAULT 0,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (snapshot_date)
);

-- Partition audit_trail by year for 7-year retention
-- (Implement via pg_partman in production)
