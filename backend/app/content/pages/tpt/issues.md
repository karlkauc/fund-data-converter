+++
title = "TPT ⇄ FundsXML conversion messages explained"
heading = "Conversion messages explained"
description = "What the messages in a TPT ⇄ FundsXML conversion report mean — missing mandatory fields, values kept as custom attributes, V8 data in the V7 block, share classes without a portfolio — and what to do about them."
lastmod = 2026-10-21
cta_label = "Convert a file"
cta_href = "/"
+++

Every conversion returns a report. Its messages have a level (*error*, *warning*, *info*) and a code; the API
returns the code, the web page shows the text. This page explains each one.

## Reading the TPT file

**Column is not a TPT field** (`unmapped_columns`) — the header of a column matches no TPT field number or name.
The column is ignored. Check for typos, or for extra columns such as internal ids.

**Column appears twice** (`duplicate_column`) — two columns map to the same field; the first one is used.

**Fields 150/151 only exist in TPT V8** (`v8_fields_in_v7`) — the file says V7 (field 1000) but has V8 columns.
The values are kept; set the version to V8 if the file really is V8.

## Writing FundsXML

**FundsXML 4.2.11 has no TPT V8 block** (`v8_in_v7_block`) — V8 data goes into the V7 block; fields 150/151, the
full version label and the codes e1/e2/e3 are kept as custom attributes. Informational; nothing is lost.
See [TPT V7 vs V8](/guides/tpt-v7-vs-v8).

**Not accepted by the TPT block** (`block_value_rejected`) and **not accepted by the core structures**
(`core_value_rejected`) — the FundsXML schema refuses the value (too long, wrong format, unknown code). It is
kept as custom attribute `TPT_<field>`, so the round trip still works, but receivers reading only the standard
elements will not see it.

**Not written to the core structures** (`core_value_skipped`) — the value has no place in the core structures
for this instrument type; it is in the TPT block.

**Differs from the first row of the portfolio** (`portfolio_value_differs`) — a portfolio field (for example
net assets, field 5) has different values within one portfolio. The first row wins; the deviating value is kept
as custom attribute. Usually a sign of two share classes sharing one ISIN in field 1.

**ControlData value rejected** (`control_data`) — a data supplier setting is invalid for FundsXML.

**Mandatory FundsXML content missing** (`schema_incomplete`) and **XSD validation errors** (`xsd_invalid`) — the
document does not validate against the FundsXML XSD, typically because the TPT lacks data FundsXML requires.
The report lists the elements.

## Reading FundsXML

**Mandatory field empty** (`mandatory_missing`) — the TPT built from the document leaves a field flagged *M*
for Solvency II empty in some rows, because the FundsXML holds no value for it and none can be derived. The
receiver will reject or query the file; add the data to the FundsXML source. The [field pages](/tpt/fields)
show which fields are mandatory and where the converter looks for them.

**Older TPT block not supported** (`older_tpt_block`) — the document has a `…_V5` or `…_V6` block; only the V7
block and the core structures are read.

**Core portfolio and TPT block differ** (`core_mismatch`) — the two hold a different number of positions, so
values from the core structures are not merged into the block's rows.

**Share class has no portfolio** (`shareclass_no_portfolio`) — neither the share class nor the fund has a
portfolio; the share class is skipped.

**Share class has no net assets** (`shareclass_inactive`) — the share class has no NAV on the valuation date,
so it is treated as inactive and skipped.

**Market values converted** (`fx_derived`) — positions lack a market value in portfolio currency (field 24);
it was converted from the fund currency at the rate the share class NAV implies.
**Market values missing** (`fx_missing`) — the same, but the NAV gives no rate, so field 24 stays empty.
