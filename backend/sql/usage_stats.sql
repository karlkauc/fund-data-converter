-- Usage statistics schema for the TPT ⇄ FundsXML Converter (docs/USAGE_STATS.md).
-- Column set is the XSD/XML/OData viewers' usage_event plus converter columns, so the
-- usage dashboard (~/webdav/usage_statistics, app key `tptconverter`) reads it with the
-- shared viewer queries. Apply once by hand as the owning role; the app never issues DDL:
--   psql "postgresql://tptconverter@62.238.116.11:5432/tptconverter_stats?sslmode=require" \
--     -f backend/sql/usage_stats.sql
-- Columns must match app/usage/events.py (UsageEvent).

CREATE TABLE IF NOT EXISTS usage_event (
  event_id         uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  received_at      timestamptz NOT NULL DEFAULT now(),
  event_type       text        NOT NULL CHECK (event_type IN ('page_view','convert','sample_load','mapping_view')),
  visitor_hash     text,                 -- sha256(daily salt | ip | user-agent), first 32 hex chars; no raw IP
  country_code     char(2),              -- ISO-3166-1 alpha-2 via GeoLite2, NULL if unknown
  user_agent       text,                 -- truncated to 255
  device           text,                 -- desktop | mobile | bot | unknown
  status_code      int,
  app_version      text,                 -- version + Cloud Run revision
  path             text,                 -- page_view: SPA route served
  referrer         text,                 -- scheme://host/path, no query
  source           text,                 -- convert: xlsx | csv | xml | sample ; sample_load: tpt-v7 | tpt-v8 | fundsxml
  schema_name      text,                 -- convert: input standard (TPT V7, FundsXML 4) – never a file name
  target_namespace text,                 -- convert: output standard (FundsXML 4, TPT V8)
  input_bytes      int,
  file_count       int,                  -- convert: portfolios (share classes)
  element_count    int,                  -- convert: positions
  type_count       int,                  -- convert TPT → FundsXML: columns in the TPT file
  diagnostic_count int,                  -- convert: messages shown to the user
  error_count      int,                  -- convert: XSD errors (TPT → FundsXML) or error messages
  duration_ms      int,
  status           text,                 -- ok | parse_error | rejected | error
  error_detail     text,                 -- exception class only, never its message
  utm_source       text,
  utm_medium       text,
  utm_campaign     text,
  direction        text,                 -- <source>-to-<target> with tpt, fundsxml, openfunds
  tpt_version      text,                 -- V7 | V8 (convert, mapping_view)
  version_source   text,                 -- TPT input: how the version was found (field, header, user, default)
  output_format    text,                 -- xml | xlsx | csv
  include_block    boolean,              -- TPT → FundsXML options
  include_core     boolean,
  issue_codes      text[]      NOT NULL DEFAULT '{}',  -- distinct Issue.code values, never messages
  valid            boolean,              -- generated FundsXML valid against the XSD
  zipped           boolean,              -- output delivered as zip
  instance         text,                 -- cloudrun | vps
  delimiter        text,                 -- CSV only: semicolon | comma | pipe | tab (TPT CSV input detected / TPT CSV output chosen)
  all_columns      boolean,              -- FundsXML → TPT option: every catalog column or only filled ones
  output_bytes     int,                  -- size of the delivered file (after zipping if zipped)
  channel          text,                 -- web (the SPA sends X-Client: web) | api
  response_mode    text                  -- convert: json | file | zip (the API's response= option)
);

CREATE INDEX IF NOT EXISTS idx_usage_event_received  ON usage_event (received_at);
CREATE INDEX IF NOT EXISTS idx_usage_event_type_time ON usage_event (event_type, received_at);
CREATE INDEX IF NOT EXISTS idx_usage_event_visitor   ON usage_event (visitor_hash);
CREATE INDEX IF NOT EXISTS idx_usage_event_country   ON usage_event (country_code);

-- ---------------------------------------------------------------------------
-- Migrations for an existing table (idempotent). Apply by hand as the owning role
-- BEFORE deploying the matching app version: INSERT_SQL names every column of
-- UsageEvent, so every insert fails until the columns exist.
-- ---------------------------------------------------------------------------

-- 2026-10-21 (T3): delimiter, all_columns, output_bytes
ALTER TABLE usage_event
  ADD COLUMN IF NOT EXISTS delimiter    text,
  ADD COLUMN IF NOT EXISTS all_columns  boolean,
  ADD COLUMN IF NOT EXISTS output_bytes int;

-- 2026-10-21 (public API): channel, response_mode
ALTER TABLE usage_event
  ADD COLUMN IF NOT EXISTS channel       text,
  ADD COLUMN IF NOT EXISTS response_mode text;
