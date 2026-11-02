# Fund Data Converter

Converts TPT, FundsXML and openfunds in every direction.

- Site: <https://www.fund-data-converter.eu>
- Repository: <https://github.com/karlkauc/fund-data-converter>

Public web app (no login) that converts between **FinDatEx TPT** files (Tripartite Template **V7** and
**V8**, XLSX or CSV), **FundsXML 4.2.11** and **openfunds 2.13** (XLSX, CSV or a ZIP of CSV files), in all
six directions. Runs as a single container on Google Cloud Run.

- **TPT → FundsXML**
  - Writes the core structures: `Funds/Fund` (identifiers, name, NAV), `Portfolio/Positions/Position`
    and `AssetMasterData/Asset` with `AssetDetails` chosen by CIC category.
  - Also writes the Solvency II block `RegulatoryReportings/IndirectReporting/TripartiteTemplateSolvencyII_V7`.
  - Validates the result against the bundled XSD.
- **FundsXML → TPT**: produces XLSX or CSV (`;` `,` `|` tab), as V7 or V8. Sources are read in this order:
  1. custom attributes
  2. the TPT block
  3. the core structures

  The rows are then fitted to the output version: a V8 file leaves the 18 fields V8 no longer maintains empty;
  a V7 file of V8 data drops 150/151 and maps e1/e2/e3 → e and issuer code type 2 → 9 (both reported).
- **Lossless round trip**: values that have no element in FundsXML, or that the schema rejects, are not
  dropped. They are stored as `Position/CustomAttributes/Attribute[Name=TPT_<field>]`. Examples: 17b, 114,
  V8 fields 150/151, V8 codes e1/e2/e3 in field 56, V8 issuer code type 2.
- **TPT versions**: V7 (25 November 2024) and the final V8 (8 October 2026). FundsXML 4.2.11 has no V8 block,
  so V8 data is written to the V7 block plus custom attributes until FundsXML 4.2.12 is released.
- **openfunds ⇄ FundsXML**
  - Share class rows are grouped into funds. Static and dynamic data use the rules in
    `app/mapping/openfunds_rules.py`.
  - `OFPH` holdings become positions: they are translated to TPT fields
    (`app/mapping/openfunds_holdings.py`) and written with the TPT core rules.
  - The EMT/EPT/EET/EFT fields go to the FundsXML template blocks (`app/mapping/openfunds_templates.json`,
    generated).
  - Every other value is kept as `CustomAttributes/Attribute[Name=OF_<OF-ID>]`.
- **TPT ⇄ openfunds** goes through FundsXML. TPT fields without an openfunds column travel as columns
  `TPT_<field>`, so TPT → openfunds → TPT is lossless.
- **Hand-over**: the result view opens generated FundsXML in [xml-viewer.online](https://www.xml-viewer.online/)
  (with the FundsXML schema from `GET /api/schema/fundsxml.zip`) and checks generated TPT files in
  [findatex-validator.eu](https://www.findatex-validator.eu/). The file goes from browser tab to browser tab
  (`window.open` + `postMessage`); it is not uploaded anywhere on the way.
- **Privacy**: files are processed in memory and never stored. No cookies, no client-side tracking.
  Usage statistics (counts, sizes, durations, issue codes – never file content, file names
  or raw IPs) and feedback go to a Postgres when `USAGE_DB_URL` is set; see `docs/USAGE_STATS.md`. Cloud Run
  request logs keep raw IPs for 30 days. `/imprint` and `/privacy` state this publicly; keep them true.

## API

Scripts use the same endpoint as the web interface. No account, no API key; the limits below apply.

```bash
# TPT → FundsXML: the XML file, key figures in X-Conversion-* headers
curl -F file=@fund.xlsx -F response=file -OJ -D - https://<host>/api/convert
# FundsXML → TPT CSV, plus report.json and issues.csv, in one zip
curl -F file=@fundsxml.xml -F output_format=csv -F response=zip -OJ https://<host>/api/convert
# TPT → openfunds (the source format is detected, target picks the output)
curl -F file=@fund.xlsx -F target=openfunds -F response=file -OJ https://<host>/api/convert
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
  app/mapping/     rules.py: every TPT field → block path + core path(s); transforms.py;
                   openfunds_rules.py, openfunds_holdings.py, openfunds_templates.(py|json)
  app/convert/     to_fundsxml.py, to_tpt.py, openfunds_to_fundsxml.py, fundsxml_to_openfunds.py, hub.py
  app/ingest/      TPT and openfunds readers (XLSX/CSV, header + delimiter detection), hardened XML parser
  app/writers/     TPT and openfunds writers
  app/spec/        TPT V7/V8 field catalogs (tools/sync_specs.py), openfunds catalog (tools/sync_openfunds.py)
  app/samples/     example files behind "Try an example" (tools/make_samples.py)
  app/usage/       usage statistics + feedback store (docs/USAGE_STATS.md)
  app/content/     server-rendered guides (pages/*.md), one page per TPT field (fields.py) and per mapped
                   openfunds field (openfunds_fields.py), home FAQ
  sql/             DDL of the usage-statistics database
frontend/  React 18 + Vite + Tailwind SPA (DE/EN, dark mode), served by FastAPI in production
e2e/       Playwright (desktop, phone, tablet)
scripts/deploy.sh  Cloud Run deployment
```

## Run locally

```bash
git clone git@github.com:karlkauc/fund-data-converter.git && cd fund-data-converter
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
GCP_PROJECT=fund-data-converter scripts/deploy.sh
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

- `SITE_ORIGIN` (default `https://www.fund-data-converter.eu`) is the indexed address: canonical links,
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
| `CONVERT_RATE_LIMIT` | 20/minute;200/hour | per client IP (X-Forwarded-For, `TRUSTED_PROXY_HOPS`); reported in `X-RateLimit-*` headers, the report's `rateLimit`, `GET /api/limits` and below the drop zone |
| `ZIP_THRESHOLD_MB` | 8 | larger outputs are zipped (Cloud Run caps responses at 32 MiB) |

Uploaded XML with a DOCTYPE or entity declaration is rejected, which rules out XXE and entity bombs.

## Updating specs and schema

- TPT catalogs: `python tools/sync_specs.py ../findatex-validator` (needs a built validator,
  `core/target/classes/spec/tpt/*.catalog.json`).
- FundsXML: replace `backend/app/schema/FundsXML4.xsd`, then run the tests. Rule paths that no longer
  exist show up as "element not in schema" messages.
- Samples: `python tools/make_samples.py ../findatex-validator` (`--synthetic` rebuilds only the files from
  `tools/sample_data.py`). A new sample also goes into `SAMPLES` (`backend/app/api/samples.py`),
  `SAMPLE_FILES` (`frontend/src/lib/api.ts`) and `SAMPLE_TEXT` (`frontend/src/lib/i18n.tsx`);
  `tests/test_samples.py` checks that the samples together cover the conditional mapping rules.
- openfunds catalog: `python tools/sync_openfunds.py [pdf-or-url]` (needs `pdftotext` from poppler-utils;
  default: the 2.13.0 field list on openfunds.org), then `python tools/build_openfunds_templates.py` to rejoin
  the template fields with the FundsXML schema. Check its "unmatched" list; `MANUAL`/`MANUAL_IDS` in the
  script take what the schema documents without (or with a wrong) number.

## License

[MIT](LICENSE)
