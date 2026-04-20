CREATE TABLE IF NOT EXISTS _rikdom_meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS portfolio_header (
  portfolio_id TEXT PRIMARY KEY,
  schema_version TEXT,
  schema_uri TEXT,
  owner_kind TEXT,
  display_name TEXT,
  country TEXT,
  base_currency TEXT,
  timezone TEXT,
  created_at TEXT,
  payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS holdings (
  holding_id TEXT PRIMARY KEY,
  portfolio_id TEXT NOT NULL,
  asset_type_id TEXT,
  label TEXT,
  ticker TEXT,
  isin TEXT,
  quantity DOUBLE,
  market_value_amount DOUBLE,
  market_value_currency TEXT,
  as_of TEXT,
  payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS snapshots (
  snapshot_ts TEXT NOT NULL,
  base_currency TEXT,
  portfolio_value_base DOUBLE,
  payload_json TEXT NOT NULL
);
