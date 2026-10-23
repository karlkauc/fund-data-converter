# Anonymous usage statistics

The converter records **aggregate, anonymous** usage so it can be improved based on real use:
how many conversions run in which direction, which TPT versions, file sizes, how long they take,
how often they fail and which conversion messages (issue codes) come up. **File content is never
stored**, and the raw client IP is neither stored nor logged. No cookies, no client-side script.

The feature is **off by default**; it only switches on when `USAGE_DB_URL` is set.

The implementation (`backend/app/usage/`) is a port of the XSD/XML/OData viewers' module. The
`usage_event` table has the same columns as theirs plus converter columns, so the usage dashboard
(`~/webdav/usage_statistics`, app key `tptconverter`, usage.status20.net) reads it with the shared
viewer queries. Both deployments (Cloud Run and the Docker copy behind www.fund-data-converter.eu)
write into the same database `tptconverter_stats` on the Hetzner Postgres (tanzapp-prod);
column `instance` tells them apart.

## What is collected

One row per event in `usage_event` (DDL: `backend/sql/usage_stats.sql`).

> **Schema changes need DDL before the deploy.** `INSERT_SQL` names every field of `UsageEvent`,
> so an app version with a new column makes **every** insert fail (events are dropped after three
> attempts) until the column exists. Apply the migration section at the end of
> `backend/sql/usage_stats.sql` by hand as the owning role first; the statements are idempotent
> (`ADD COLUMN IF NOT EXISTS`). Pending since 2026-10-21: `delimiter`, `all_columns`,
> `output_bytes`, `channel`, `response_mode` —
>
> ```sql
> ALTER TABLE usage_event
>   ADD COLUMN IF NOT EXISTS delimiter    text,
>   ADD COLUMN IF NOT EXISTS all_columns  boolean,
>   ADD COLUMN IF NOT EXISTS output_bytes int;
> ALTER TABLE usage_event
>   ADD COLUMN IF NOT EXISTS channel       text,
>   ADD COLUMN IF NOT EXISTS response_mode text;
> ```


| `event_type` | Emitted by | |
|---|---|---|
| `page_view` | `spa.py`, a known route's HTML shell | `path`, `utm_*`; client-side navigation is not counted |
| `convert` | `POST /api/convert` | one per upload, including rejected ones |
| `sample_load` | `GET /api/samples/{name}` | `source` = sample name, `<name>:download` for `?download=1` |
| `mapping_view` | `GET /api/mapping/{version}` | `tpt_version` |

| Column | Meaning |
|---|---|
| `visitor_hash` | `sha256(daily_salt ‖ ip ‖ user-agent)[:32]`; salt = `HMAC(USAGE_HASH_SECRET, UTC date)`: same visitor within a day, unlinkable across days, not reversible |
| `country_code` | ISO-3166-1 alpha-2 via MaxMind GeoLite2; NULL if unknown |
| `user_agent`, `device` | UA (≤255) and `desktop`/`mobile`/`bot`/`unknown` |
| `referrer` | `scheme://host/path` of the Referer, no query (the site itself sends `Referrer-Policy: no-referrer`) |
| `direction` | `<source>-to-<target>` over `tpt`, `fundsxml`, `openfunds` (six directions) |
| `source_format`, `target_format` | the two halves of `direction`, also on failed conversions, downloads and hand-overs |
| `source` | convert: input format `xlsx`/`csv`/`xml`, or `sample` when the upload is a bundled example (compared by hash). A failed conversion takes it from the file extension (`.xlsx`/`.xls` → `xlsx`, `.csv`, `.xml`; NULL for anything else unless the content is XML) |
| `schema_name`, `target_namespace` | input and output standard, e.g. `TPT V7` → `FundsXML 4` |
| `tpt_version`, `version_source` | V7/V8; for TPT input how the version was found (`field 1000`, `default`, `user` …). A failed conversion records the *requested* version (NULL = auto) |
| `output_format` | `xml` / `xlsx` / `csv` |
| `include_block`, `include_core` | TPT → FundsXML options |
| `input_bytes`, `duration_ms` | upload size, conversion time |
| `file_count`, `element_count`, `type_count` | portfolios (share classes), positions, TPT columns |
| `diagnostic_count`, `error_count` | messages shown; XSD errors (TPT → FundsXML) or error messages |
| `issue_codes` | distinct `Issue.code` values (`mandatory_missing`, `xsd_invalid` …), never the messages |
| `valid`, `zipped` | generated FundsXML valid against the XSD; output delivered as zip |
| `output_bytes` | size of the delivered file (after zipping when `zipped`) |
| `delimiter` | CSV only: `semicolon`/`comma`/`pipe`/`tab` — detected in a TPT CSV upload, or chosen for a TPT CSV output (an unknown choice is written as `semicolon`); NULL for xlsx/xml |
| `all_columns` | FundsXML → TPT option: every catalog column (`true`) or only the filled ones; NULL for TPT → FundsXML |
| `status`, `status_code`, `error_detail` | `ok` / `parse_error` / `rejected` (position limit, 400, 413, 429) / `error` (5xx); `error_detail` is the exception **class** only (`TptReadError` …), because messages may quote file values; a request the handler refuses before converting carries a fixed code (`too_large`, `empty_file`, `bad_tpt_version`, `nothing_selected`) together with `direction`, `source`, the requested `tpt_version` and `input_bytes` as far as the upload tells them. Rows refused before the handler (body limit, 429, malformed form) have no `direction` — the dashboard labels them "rejected before processing" |
| `instance` | `cloudrun` / `vps` (`USAGE_INSTANCE`) |
| `channel` | `web` when the request carries `X-Client: web` (only the SPA sends it), else `api`. API scripts are usually also `device = bot` (curl, python-requests …), so filter API use by `channel`, not by `device` |
| `response_mode` | convert: the API's `response=` option, `json` / `file` / `zip` |
| `of_layout`, `of_templates` | openfunds input: `flat`/`narrow`; FinDatEx templates (`EMT`, `EPT`, `EET`, `EFT`) with at least one filled field |
| `shareclass_count`, `holding_count`, `asset_count` | openfunds input: share classes and OFPH rows; FundsXML input: share classes and `AssetMasterData/Asset` |
| `has_tpt_block` | FundsXML input carries the Solvency II TPT block |
| `cic_categories` | the CIC *categories* present (third character: `1` government bonds … `7` cash, `A`–`F` derivatives), from the TPT rows, the openfunds holding CIC or the FundsXML asset classifications – no codes, no values |
| `warning_count`, `info_count` | messages by level (`diagnostic_count` is all of them) |
| `values_lost`, `values_kept_custom` | the report's `dataLoss`: values lost / kept as custom attributes |
| `coverage_pct` | → FundsXML: share of the source fields placed in the TPT block or core structures (the rest went to custom attributes) |
| `options` | options set away from their default that apply to the direction, as fixed names: `tpt_version_forced`, `of_header_names`, `no_non_openfunds_columns`, `no_implied_tpt_attributes`, `data_supplier`, `no_preview` |
| `isin_countries`, `nav_months`, `data_age_days` | of the share classes converted: the ISINs' country prefixes (`LU`, `IE` …), the valuation months (`2026-09`) and the days from the latest valuation date to the conversion – never an ISIN or a date |
| `fund_keys` | per share class ISIN `HMAC-SHA256(USAGE_HASH_SECRET, "fund|" + ISIN)[:20]`: stable across days, so distinct and repeatedly converted funds can be counted; without the secret it can neither be reversed nor matched against an ISIN list. Empty without a secret |
| `target` | `download`: file type `xml`/`xlsx`/`csv`/`zip`; `handoff`: `validator`/`xml-viewer` |
| `app_version`, `received_at` | version + Cloud Run revision (VPS: git commit), server timestamp |

**Browser events.** `download` and `handoff` come from the SPA via `POST /api/usage/event`
(`backend/app/api/usage.py`, 60/minute): only fixed values – the type, `target`, `direction` and for a
hand-over `status` = `ok` (posted) / `timeout` (the other tab never answered) / `blocked` (no popup).
Anything else is refused with 422. They let the dashboard follow a conversion to its use.

**Never collected:** file content, file names, portfolio ids/names/NAVs, cell values, issue
messages, raw IP, cookies.

### Feedback

`POST /api/feedback` (dialog behind the footer link and "Report a problem" on errors) writes one
row to `feedback` (`backend/sql/feedback.sql`): `message`, optional `email`, `page`, `direction`,
`tpt_version`, `error_detail` (the error the user was looking at), plus `visitor_hash`,
`country_code`, `user_agent`, `device`, `app_version`. Without a database the feedback is logged at
WARNING level instead. Rate limit 5/minute; a honeypot field drops naive bots.

## Architecture

```
request → usage_context middleware (app/main.py) binds RequestUsage(ip, ua, referrer)
        → route calls emit("convert", …)              (app/usage/context.py)
        → UsageRecorder queue (in-memory, 1000)       (app/usage/recorder.py)
        → background task: batched INSERT via psycopg, 3 attempts, then drop
```

- `emit()` never raises and is a no-op without a tracker. Requests to `/api/convert` that are
  turned away before the handler (413, 429, malformed form, crash) are recorded by the middleware;
  refusals inside the handler go through `_reject()` in `app/api/convert.py`.
- On Cloud Run the CPU is throttled once the response is sent, so the middleware waits (bounded by
  `USAGE_DRAIN_SECONDS`, default 2 s) for pending writes before returning a response that emitted
  events. On shutdown the lifespan flushes for ≤ 5 s.
- GeoLite2-Country is downloaded by `scripts/deploy.sh` into `backend/geoip/` and baked into the
  image. Without the file the app downloads it at startup when `MAXMIND_LICENSE_KEY` is set
  (Docker copy); otherwise `country_code` stays NULL.

Attribution: "This product includes GeoLite2 data created by MaxMind, available from
https://www.maxmind.com."

## Configuration

| Env | |
|---|---|
| `USAGE_DB_URL` | `postgresql://tptconverter@62.238.116.11:5432/tptconverter_stats?sslmode=require`; empty = off |
| `USAGE_DB_PASSWORD` | secret |
| `USAGE_HASH_SECRET` | secret; **same value on both deployments** |
| `USAGE_INSTANCE` | `cloudrun` / `vps` |
| `MAXMIND_LICENSE_KEY`, `GEOIP_DB_PATH` | GeoLite2 download key, file path (`/app/geoip/GeoLite2-Country.mmdb`) |
| `USAGE_DRAIN_SECONDS` | default 2 |

## One-time setup

1. **Database** (tanzapp-prod, as postgres superuser):
   ```sql
   CREATE ROLE tptconverter LOGIN PASSWORD '<openssl rand -hex 24>';
   CREATE DATABASE tptconverter_stats OWNER tptconverter;
   ```
   Store the password in `/home/deploy/tptconverter-db-password.txt`; add a `pg_hba.conf`
   `hostssl tptconverter_stats tptconverter 0.0.0.0/0 scram-sha-256` line like the viewers' if
   connections are restricted per database. Then, as the owning role (it must own the tables,
   because the dashboard's maintenance page runs DELETE and VACUUM):
   ```bash
   psql "postgresql://tptconverter@62.238.116.11:5432/tptconverter_stats?sslmode=require" \
     -f backend/sql/usage_stats.sql -f backend/sql/feedback.sql
   ```
2. **Cloud Run secrets** (values via stdin, not on the command line):
   ```bash
   P=<project-id>
   printf '%s' '<db-password>'   | gcloud secrets create tptconverter-db-password --project "$P" --data-file=-
   openssl rand -hex 32 | tr -d '\n' | gcloud secrets create tptconverter-usage-hash-secret --project "$P" --data-file=-
   printf '%s' '<maxmind-key>'   | gcloud secrets create tptconverter-maxmind-license-key --project "$P" --data-file=-
   SA=$(gcloud run services describe fund-data-converter --project "$P" --region europe-west1 \
          --format='value(spec.template.spec.serviceAccountName)')
   for s in tptconverter-db-password tptconverter-usage-hash-secret tptconverter-maxmind-license-key; do
     gcloud secrets add-iam-policy-binding "$s" --project "$P" \
       --member="serviceAccount:$SA" --role=roles/secretmanager.secretAccessor
   done
   ```
   `scripts/deploy.sh` enables the statistics as soon as `tptconverter-db-password` exists.
3. **Docker copy** (www.fund-data-converter.eu): `cp .env.example .env`, fill in the password, the
   hash secret (`gcloud secrets versions access latest --secret tptconverter-usage-hash-secret`)
   and the MaxMind key, then `docker compose up -d --build`.
4. **Dashboard**: register the app in `~/webdav/usage_statistics` (`TPTCONVERTER_DB_URL` /
   `TPTCONVERTER_DB_PASSWORD` in its `.env`).

The app never issues DDL. A new column means: `ALTER TABLE` here first, then the dashboard, then the
converter (`UsageEvent` in `app/usage/events.py` lists the columns in insert order).
