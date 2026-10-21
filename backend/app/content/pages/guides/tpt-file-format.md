+++
title = "TPT file format: Excel and CSV layout, headers, delimiters"
heading = "The TPT file format: Excel and CSV"
description = "How a Tripartite Template file is laid out: one row per position, column headers, CSV delimiters and encodings, number and date formats — and what the converter accepts."
lastmod = 2026-10-21
cta_label = "Convert a TPT file"
cta_href = "/"
+++

FinDatEx defines the fields of the Tripartite Template, not a file format. In practice a TPT is exchanged as an
**Excel workbook** or a **CSV file** with one header row and one row per position.

## Rows and columns

- **One row per position.** The portfolio fields (1–11 and 115–126) repeat on every row of the same portfolio.
- **One portfolio per share class.** Field 1 holds the share class ISIN; a file may contain several portfolios
  and several valuation dates (field 6). The converter groups rows by field 1 and field 6.
- **Columns** are identified by their header. Producers write `12`, `12_CIC_code_of_the_instrument` or just
  `CIC code of the instrument`; the converter accepts all three, ignoring case and punctuation. Unknown columns
  are reported and skipped.
- **The header row** need not be the first: the converter takes the first of the first 50 rows in which at least
  three cells are TPT field names, so title rows and notes above the table are fine.

## CSV specifics

- **Delimiter:** semicolon, comma, pipe or tab, detected from the header lines. A `sep=;` first line, as Excel
  writes it, is honoured.
- **Encoding:** UTF-8 (with or without BOM), otherwise Windows-1252.
- **Output:** FundsXML → TPT writes CSV as UTF-8 with BOM so Excel opens it correctly, separated by semicolon
  unless you choose comma, pipe or tab.

## Values

- **Numbers** use a dot as decimal separator; weights and rates are fractions (0.05 = 5 %).
- **Dates** are ISO 8601 (`YYYY-MM-DD`).
- **Codes** come from closed lists — for example [field 2](/tpt/fields/2-type-of-identification-code-for-the-fund-share-or-portfolio)
  or the [CIC code](/tpt/fields/12-cic-code-of-the-instrument). [All TPT fields](/tpt/fields) lists the allowed
  values per field.

## Version

Field 1000 states the template version. Without it, a column 150 or 151 identifies V8; otherwise the file is read
as V7. See [TPT V7 vs V8](/guides/tpt-v7-vs-v8).
