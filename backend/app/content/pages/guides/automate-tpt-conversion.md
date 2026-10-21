+++
title = "Automate TPT conversion: FundsXML ⇄ TPT via API"
heading = "Automate TPT ⇄ FundsXML conversion"
description = "Convert Tripartite Template files to FundsXML 4 and back from scripts and pipelines: one HTTP POST with curl, PowerShell or Python, the result file plus a JSON report. No account, no API key."
lastmod = 2026-10-21
cta_label = "Read the API documentation"
cta_href = "/api-docs"

[[faq]]
q = "Do I need an API key?"
a = "No. The API is the same endpoint the web page uses. It is limited to 20 conversions per minute per client, 25 MB per file and 10,000 positions per conversion."

[[faq]]
q = "How do I know whether a conversion lost data?"
a = "The JSON report has `dataLoss` (values lost or kept only as custom attributes) and `validation`; with `response=file` the same key figures arrive in `X-Conversion-Data-Lost` and `X-Conversion-Valid` headers."
+++

Monthly TPT deliveries for dozens of share classes are a job for a script, not for a browser. The converter
exposes its conversion as **one HTTP request**: `POST /api/convert` with the file as multipart form data. The
direction follows from the file — a TPT (XLSX/CSV) becomes FundsXML, a FundsXML document becomes TPT.

## curl

```bash
API={{origin}}/api/convert

# TPT → FundsXML: save the XML and print the X-Conversion-* headers
curl -sS --fail-with-body -F file=@fund.xlsx -F response=file -OJ -D - "$API"

# FundsXML → TPT V8 as CSV: file, report.json and issues.csv in one zip
curl -sS --fail-with-body -F file=@fundsxml.xml -F tpt_version=V8 \
  -F output_format=csv -F response=zip -OJ "$API"
```

## Python

```python
import base64, requests

with open("fund.xlsx", "rb") as f:
    r = requests.post("{{origin}}/api/convert", files={"file": f}, data={"preview": "false"}, timeout=120)
r.raise_for_status()
report = r.json()
with open(report["output"]["filename"], "wb") as out:
    out.write(base64.b64decode(report["output"]["base64"]))
print(report["validation"]["valid"], report["issueCounts"], report["dataLoss"])
```

## What comes back

- `response=json` (default): the report with the converted file base64-encoded.
- `response=file`: the converted file; key figures in `X-Conversion-*` headers (portfolios, positions, valid,
  warnings, errors, data lost).
- `response=zip`: the file, `report.json` and `issues.csv` together.

The report holds the XSD validation result, `issueCounts`, every message (see [conversion messages](/tpt/issues)),
`dataLoss` and `meta` with versions, SHA-256 of input and output and the duration.

## Options

| Field | Values | Direction |
|---|---|---|
| `tpt_version` | `V7`, `V8` | both: force the input version, or choose the output version |
| `include_block`, `include_core` | `true`/`false` | TPT → FundsXML |
| `output_format` | `xlsx`, `csv` | FundsXML → TPT |
| `delimiter` | `semicolon`, `comma`, `pipe`, `tab` | FundsXML → TPT, CSV |
| `all_columns` | `true`/`false` | FundsXML → TPT |

The [API documentation](/api-docs) has PowerShell examples and every field; the OpenAPI description is at
[/api/docs](/api/docs).
