+++
title = "TPT V7 vs V8: what changed in the Tripartite Template"
heading = "TPT V7 vs TPT V8"
description = "The differences between Tripartite Template V7 and V8 field by field: new fields 150 and 151, securitisation codes e1–e3 in field 56, and how FundsXML 4 handles V8 data."
lastmod = 2026-10-21
cta_label = "Convert a TPT V7 or V8 file"
cta_href = "/"

[[faq]]
q = "Can a V8 file be converted to FundsXML 4.2.11?"
a = "Yes. FundsXML 4.2.11 only has a V7 block, so V8 data goes into it and the V8-only values are kept as custom attributes `TPT_<field>`. Converting back to TPT V8 restores the original file."

[[faq]]
q = "How does the converter tell V7 from V8?"
a = "From field 1000 (the template version, e.g. `V8.0`); without it, the presence of column 150 or 151 means V8, otherwise V7. You can also choose the version by hand."
+++

FinDatEx published **TPT V8** (official version dated 26 May 2026) as the successor of **TPT V7** (25 November
2024). V8 keeps the structure of V7: the same 152 fields with the same numbers, plus two new ones.

## The changes

| Field | Change in V8 |
|---|---|
| [150 – LTEI fund eligibility](/tpt/fields/150-ltei-fund-elligibility) | New. Whether a held fund is eligible under the long-term equity investment rules (0 not assessed, 1 eligible, 2 not eligible). For CIC 3 and 4. |
| [151 – Legislative program investment](/tpt/fields/151-legislative-program-investment) | New. Whether held equities are eligible under legislative programmes. For CIC 3. |
| [56 – Securitisation](/tpt/fields/56-securitisation) | Code `e` is split into `e1`, `e2` and `e3`. |
| [115](/tpt/fields/115-fund-issuer-code) / [119](/tpt/fields/119-fund-issuer-group-code) – fund issuer (group) code | Definition shortened to "LEI"; V7 said "LEI when available, otherwise not reported". |
| [1000 – TPT version](/tpt/fields/1000-tpt-version) | Holds the V8 label. |

Every field page shows the definition, flags and codes of the current version and points out where V7
differs.

## V8 in FundsXML 4

FundsXML 4.2.11 has a Solvency II block for V7 only (`TripartiteTemplateSolvencyII_V7`). The converter therefore
writes V8 files into that block and keeps what the block cannot hold:

- fields 150 and 151,
- the codes e1/e2/e3 of field 56 (the block receives `e`),
- the full version label of field 1000,

as custom attributes named `TPT_<field>` on the position or fund. Converting the document back to TPT V8 reads
these attributes first, so the round trip is lossless. The conversion report says so in the message
*"FundsXML 4.2.11 has no TPT V8 block"* — see [conversion messages](/tpt/issues).

## Converting between V7 and V8

FundsXML → TPT can write either version. Choosing V7 for a document that holds V8 data drops 150/151 and maps
e1–e3 back to `e`; the report lists the values that were lost.
