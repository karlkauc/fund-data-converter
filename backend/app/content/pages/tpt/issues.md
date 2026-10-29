+++
title = "TPT ⇄ FundsXML ⇄ openfunds conversion messages explained"
heading = "Conversion messages explained"
description = "What the messages in a TPT ⇄ FundsXML conversion report mean — missing mandatory fields, values kept as custom attributes, V8 data in the V7 block, share classes without a portfolio — and what to do about them."
lastmod = 2026-10-22
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

**Values in fields TPT V8 no longer maintains** (`v8_not_applicable`) — a V8 file fills one of the 18 fields
FinDatEx retired in V8 (17b, 29, 31, 35, 36, 44, 54, 58b, 106, 108, 114, 116, 118, 120, 124, 125, 126, 141).
They must be empty in V8. The values still reach FundsXML, but a V8 output leaves them out.

## Writing FundsXML

**FundsXML 4.2.11 has no TPT V8 block** (`v8_in_v7_block`) — V8 data goes into the V7 block; fields 150/151, the
full version label, the codes e1/e2/e3 and the issuer code type 2 are kept as custom attributes, and the
elements the V7 block requires but V8 no longer has (116/120/141, 118, 36, 44) are filled from the V8 data.
Informational; nothing is lost. See [TPT V7 vs V8](/guides/tpt-v7-vs-v8).

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

**TPT V8 no longer maintains field(s)** (`v8_not_applicable_dropped`) — the output is V8, and the document holds
V7 data with values for fields V8 requires to be empty (typically the code types 116/120 or the NACE sector 54).
They are left out of the file; the message counts them. Choose V7 if you need them. For V8 data the fields are
dropped silently: they hold only what the V7 block required or what was already reported when the file was read.

**V8 value(s) adapted for TPT V7** (`v7_downgrade`) — the output is V7, but the document holds V8 data: fields
150/151 are left out, securitisation codes e1/e2/e3 are written as `e`, and the issuer code type 2 (external
identifier) as 9. Choose V8 to keep them.

**Core portfolio and TPT block differ** (`core_mismatch`) — the two hold a different number of positions, so
values from the core structures are not merged into the block's rows.

**Share class has no portfolio** (`shareclass_no_portfolio`) — neither the share class nor the fund has a
portfolio; the share class is skipped.

**Share class has no net assets** (`shareclass_inactive`) — the share class has no NAV on the valuation date,
so it is treated as inactive and skipped.

**Market values converted** (`fx_derived`) — positions lack a market value in portfolio currency (field 24);
it was converted from the fund currency at the rate the share class NAV implies.
**Market values missing** (`fx_missing`) — the same, but the NAV gives no rate, so field 24 stays empty.

## Reading openfunds

**OF-ID not in openfunds** (`of_unknown_field`) — a column header looks like an OF-ID that the current openfunds
version does not define. The values are kept as they are (custom attribute `OF_<column>`).

**Revoked field** (`of_revoked_field`) — the field was withdrawn in a newer openfunds version. Its values are kept.

**Not an openfunds field** (`of_non_openfunds_column`) — the column has no OF-ID (openfunds `OFST999990`). It is
kept under its header name and written back unchanged.

**[IGNORE] values** (`of_ignore_value`) — openfunds uses `[IGNORE]` for "do not overwrite". These cells are treated
as not delivered.

**Value given twice** (`of_value_conflict`) — rows of the same share class (narrow layout) give different values
for one field. The first one is used.

**Value does not fit the field** (`of_value_invalid`) — not a number, date, yes/no or code of the field's list. The
value is still converted; the receiver may reject it.

**Holding without share class** (`of_holding_unassigned`) — a holding names no share class of the file in
`OFST020000`, and the file has several share classes. It cannot be placed and is not converted.

## Writing FundsXML from openfunds

**Differs from the fund's first share class** (`of_fund_value_differs`) — a fund-level field (for example the
domicile) differs between share classes of one fund. The first share class's value goes to the fund; the other
is kept as custom attribute of its share class.

**Template data incomplete** (`of_template_incomplete`) — the EMT, EPT, EET or EFT block needs fields the file does
not have. The block is not written; its values are kept as custom attributes. The message names the missing
elements.

**Not accepted by the template block** (`of_template_rejected`) and **lost** (`of_value_lost`) — the schema refused
a value; it is kept as custom attribute, or, if even that is refused (an over-long column name), lost.

## Converting between TPT and openfunds

**Fields the other format has no place for** (`hop_data_loss`) — TPT ⇄ openfunds goes through FundsXML. openfunds
static data without a TPT field, or TPT fields without an openfunds column (when the `TPT_<field>` columns are
switched off), are not in the output. See [TPT ⇄ openfunds](/guides/tpt-to-openfunds).

**Umbrella structures not read** (`of_subfunds_skipped`) — FundsXML `Fund/Subfunds` are not converted to openfunds;
single funds and their share classes are.
