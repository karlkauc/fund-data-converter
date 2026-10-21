# TPT ⇄ FundsXML Converter

Public web app (no login) that converts **FinDatEx TPT** files (Tripartite Template **V7** and **V8**,
XLSX or CSV) to **FundsXML 4.2.11** and back. Runs as a single container on Google Cloud Run.

- **TPT → FundsXML**
  - Writes the core structures: `Funds/Fund` (identifiers, name, NAV), `Portfolio/Positions/Position`
    and `AssetMasterData/Asset` with `AssetDetails` chosen by CIC category.
  - Also writes the Solvency II block `RegulatoryReportings/IndirectReporting/TripartiteTemplateSolvencyII_V7`.
  - Validates the result against the bundled XSD.
- **FundsXML → TPT**: produces XLSX or CSV (`;` `,` `|` tab), as V7 or V8. Sources are read in this order:
  1. custom attributes
  2. the TPT block
  3. the core structures
- **Lossless round trip**: values that have no element in FundsXML, or that the schema rejects, are not
  dropped. They are stored as `Position/CustomAttributes/Attribute[Name=TPT_<field>]`. Examples: 17b, 114,
  V8 fields 150/151, V8 codes e1/e2/e3 in field 56.
- **Privacy**: files are processed in memory and never stored. No cookies, no client-side tracking.
  Anonymous usage statistics (counts, sizes, durations, issue codes – never file content, file names
  or IPs) and feedback go to a Postgres when `USAGE_DB_URL` is set; see `docs/USAGE_STATS.md`.

## API

Scripts use the same endpoint as the web interface. No account, no API key; the limits below apply.

```bash
# TPT → FundsXML: the XML file, key figures in X-Conversion-* headers
curl -F file=@fund.xlsx -F response=file -OJ -D - https://<host>/api/convert
# FundsXML → TPT CSV, plus report.json and issues.csv, in one zip
curl -F file=@fundsxml.xml -F output_format=csv -F response=zip -OJ https://<host>/api/convert
```

`response=json` (the default) returns the report with the file base64-encoded. Besides the conversion
messages, the report holds `validation`, `issueCounts`, `dataLoss` (TPT values lost or only kept as
custom attributes) and `meta` (versions, sha256 of input and output, duration). Documentation with
PowerShell and Python examples is at `/api-docs`, and the OpenAPI description at `/api/docs`.

## Layout

```
backend/   FastAPI app (Python 3.12, lxml, openpyxl)
  app/schema/      bundled FundsXML4.xsd + compact schema model (child order, required, facets)
  app/model/       schema-guided XML builder (ordering, value normalisation, pruning, reporting)
  app/mapping/     rules.py: every TPT field → block path + core path(s); transforms.py
  app/convert/     to_fundsxml.py, to_tpt.py
  app/ingest/      TPT reader (XLSX/CSV, header + delimiter + version detection), hardened XML parser
  app/spec/        TPT V7/V8 field catalogs (from findatex-validator, tools/sync_specs.py)
  app/samples/     example files behind "Try an example" (tools/make_samples.py)
  app/usage/       anonymous usage statistics + feedback store (docs/USAGE_STATS.md)
  app/content/     server-rendered guides (pages/*.md), one page per TPT field (fields.py), home FAQ
  sql/             DDL of the usage-statistics database
frontend/  React 18 + Vite + Tailwind SPA (DE/EN, dark mode), served by FastAPI in production
e2e/       Playwright (desktop, phone, tablet)
scripts/deploy.sh  Cloud Run deployment
```

## Run locally

```bash
python3 -m venv .venv && .venv/bin/pip install -e "backend[dev]"
cd frontend && npm ci && npm run build && cd ..
cd backend && STATIC_DIR=../frontend/dist TRUSTED_PROXY_HOPS=0 ../.venv/bin/uvicorn app.main:app --port 8080
# frontend dev server with hot reload (proxies /api to :8080): cd frontend && npm run dev
```

## Tests

```bash
cd backend && ../.venv/bin/pytest && ../.venv/bin/ruff check . && ../.venv/bin/ruff format --check .
cd frontend && npx tsc -b && npm run lint && npm test
cd e2e && npm install && npx playwright install chromium && PATH=../.venv/bin:$PATH npx playwright test
```

The round-trip tests (`backend/tests/test_roundtrip.py`) convert every fixture TPT → FundsXML → TPT and
require identical values (numbers and dates compared by value).

## Deploy (Google Cloud Run)

```bash
GCP_PROJECT=<project-id> scripts/deploy.sh
```

The script runs `gcloud run deploy --source .`, using the `Dockerfile` via Cloud Build. Settings:

- Region `europe-west1`, `--allow-unauthenticated`.
- `--memory 1Gi --cpu 1 --cpu-boost --concurrency 4`.
- `--min-instances 0 --max-instances 4 --timeout 60`.

With `min-instances 0` the service costs nothing while idle. The script finishes with a smoke test against
the service URL.

Usage statistics switch on once the Secret Manager secrets from `docs/USAGE_STATS.md` exist; the script
then also downloads GeoLite2 into `backend/geoip/` and mounts the secrets. The Docker copy
(`docker-compose.yml`) reads the same settings from `.env` (see `.env.example`).

### Search engines

- `SITE_ORIGIN` (default `https://converter.status20.net`) is the indexed address: canonical links,
  `og:url`, `/sitemap.xml`, `/robots.txt` and `/llms.txt` use it. Every other host – the `*.run.app` URL,
  staging – gets `X-Robots-Tag: noindex`. Set it in `deploy.sh`'s environment and in `.env`.
- Content pages live in `backend/app/content/`: Markdown with TOML front matter under `pages/`, the
  generated field pages in `fields.py`, the home FAQ in `faq.toml`. `pages.py`, `render.py` and
  `template.html` are shared with the sister sites (xsd/xml/odata viewer); keep them in step.
- After a deploy with new pages: `python3 tools/indexnow_ping.py --key $INDEXNOW_KEY --site $SITE_ORIGIN`.
- `tools/generate_og_image.py` renders `og-image.png` and `apple-touch-icon.png`.

### Limits and abuse protection

| Setting (env) | Default | Why |
|---|---|---|
| `MAX_UPLOAD_MB` | 25 | request size; larger bodies get 413 without being buffered |
| `MAX_POSITIONS` | 10000 | ~800 MB peak and ~11 s for 10,000 positions |
| `MAX_CONCURRENT_CONVERSIONS` | 1 | conversions per instance; the next upload waits or goes to another instance |
| `CONVERT_RATE_LIMIT` | 20/minute | per client IP (X-Forwarded-For, `TRUSTED_PROXY_HOPS`) |
| `ZIP_THRESHOLD_MB` | 8 | larger outputs are zipped (Cloud Run caps responses at 32 MiB) |

Uploaded XML with a DOCTYPE or entity declaration is rejected, which rules out XXE and entity bombs.

## Updating specs and schema

- TPT catalogs: `python tools/sync_specs.py ../findatex-validator` (needs a built validator,
  `core/target/classes/spec/tpt/*.catalog.json`).
- FundsXML: replace `backend/app/schema/FundsXML4.xsd`, then run the tests. Rule paths that no longer
  exist show up as "element not in schema" messages.
- Samples: `python tools/make_samples.py ../findatex-validator`.
