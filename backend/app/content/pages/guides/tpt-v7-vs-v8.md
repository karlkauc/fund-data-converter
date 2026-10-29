+++
title = "TPT V7 vs V8: what changed in the Tripartite Template"
heading = "TPT V7 vs TPT V8"
description = "The differences between Tripartite Template V7 and the final V8 (8 October 2026) field by field: new fields 150 and 151, 18 fields no longer maintained, mandatory issuer identifiers with code type 2, securitisation codes e1–e3, the timeline, and how FundsXML 4 handles V8 data."
lastmod = 2026-10-29
cta_label = "Convert a TPT V7 or V8 file"
cta_href = "/"

[[faq]]
q = "When does TPT V8 become mandatory?"
a = "FinDatEx's timeline: the December 2026 production still uses V7, January and February 2027 allow V7 or V8 in parallel, and from the end-of-March 2027 production V8 is mandatory."

[[faq]]
q = "Can a V8 file be converted to FundsXML 4.2.11?"
a = "Yes. FundsXML 4.2.11 only has a V7 block, so V8 data goes into it and the V8-only values are kept as custom attributes `TPT_<field>`. Converting back to TPT V8 restores the original file."

[[faq]]
q = "How does the converter tell V7 from V8?"
a = "From field 1000 (the template version, e.g. `V8.0`); without it, the presence of column 150 or 151 means V8, otherwise V7. You can also choose the version by hand."

[[faq]]
q = "What happens to the fields V8 no longer maintains?"
a = "A V8 file written by the converter leaves the 18 fields empty, as the Technical Annex requires; the report lists the values that were left out. A V8 input that still fills them is converted with a warning."
+++

FinDatEx published the final **TPT V8** on 28 October 2026 (official version dated 8 October 2026) as the successor
of **TPT V7** (25 November 2024). V8 keeps the column layout of V7: no field is physically removed, two conditional
fields are appended, and field 1000 must read `V8.0 (official) dated 8 October 2026`. The public consultation draft
of May 2026 is superseded.

## Timeline

| Production | Template version |
|---|---|
| December 2026 | V7 |
| January and February 2027 | V7 or V8 in parallel |
| From end-March 2027 | V8 mandatory |

## The changes

| Field | Change in V8 |
|---|---|
| [150 – LTEI fund eligibility](/tpt/fields/150-ltei-fund-eligibility) | New, conditional. Whether a held fund without look-through qualifies for the long-term equity regime (Art. 171a Delegated Regulation (EU) 2015/35): `0` not assessed, `1` eligible, `2` not eligible. For CIC 3 and 4. |
| [151 – Legislative program investment](/tpt/fields/151-legislative-program-investment) | New, conditional. Whether held equities qualify for a legislative programme (Art. 173): same codes. For CIC 3. |
| 18 fields retained but no longer maintained | [17b](/tpt/fields/17b-asset-liability), [29](/tpt/fields/29-market-exposure-amount-for-the-3rd-quotation-currency-c), [31](/tpt/fields/31-market-exposure-for-the-3rd-currency-in-weight-over-nav), [35](/tpt/fields/35-identification-type-for-interest-rate-index), [36](/tpt/fields/36-interest-rate-index-name), [44](/tpt/fields/44-issuer-bearer-option-exercise), [54](/tpt/fields/54-economic-sector), [58b](/tpt/fields/58b-nature-of-the-tranche), [106](/tpt/fields/106-asset-pledged-as-collateral), [108](/tpt/fields/108-participation), [114](/tpt/fields/114-issuer-economic-area), [116](/tpt/fields/116-fund-issuer-code-type), [118](/tpt/fields/118-fund-issuer-sector), [120](/tpt/fields/120-fund-issuer-group-code-type), [124](/tpt/fields/124-duration), [125](/tpt/fields/125-accrued-income-security-denominated-currency), [126](/tpt/fields/126-accrued-income-portfolio-denominated-currency), [141](/tpt/fields/141-type-of-custodian-identification-code). The columns stay, but **must be left empty**; deletion in 2028 is under consideration. |
| [47](/tpt/fields/47-issuer-identification-code) / [48](/tpt/fields/48-type-of-identification-code-for-issuer), [50](/tpt/fields/50-identification-of-the-group) / [51](/tpt/fields/51-type-of-identification-code-for-issuer-group), [81](/tpt/fields/81-issuer-identification-code-of-the-underlying-asset) / [82](/tpt/fields/82-type-of-issuer-identification-code-of-the-underlying-asset), [84](/tpt/fields/84-identification-of-the-group-of-the-underlying-asset) / [85](/tpt/fields/85-type-of-the-group-identification-code-of-the-underlying-asset) – issuer and group identification | Now **mandatory** (47/48/50/51 for every CIC category, including CIC 0). The code type gets a new list: `1` LEI, `2` external identifier, `9` internal identifier — in that order of priority. The external identifier is the VAT ID for issuers in the EEC, otherwise the ISO 3166-1 alpha-2 country code followed by the national registration number (for example `US` + Employer Identification Number). **In V7, `9` meant "none"**; mapping tables need updating. |
| [115](/tpt/fields/115-fund-issuer-code), [119](/tpt/fields/119-fund-issuer-group-code), [140](/tpt/fields/140-custodian-identification-code) – fund issuer, fund issuer group and custodian codes | Must contain LEIs; the code type columns 116, 120 and 141 are no longer maintained. |
| [56 – Securitisation](/tpt/fields/56-securitisation) | Code `e` is split into `e1` (senior non-STS, Art. 178 (8)), `e2` (junior non-STS, Art. 178 (8a)) and `e3` (other, Art. 178 (9)). |
| [62 – Conversion factor](/tpt/fields/62-conversion-factor) | Renamed from `62_Conversion_factor_(convertibles)_concordance_factor_parity_(options)`; limited to convertible bonds, no longer filled for options or derivatives. |
| [148 – Economic sector NACE](/tpt/fields/148-economic-sector-nace) | Renamed from `148_Economic_sector_NACE2.1`; uses the latest NACE version in force. |
| [127](/tpt/fields/127-bond-floor-convertible-instrument-only) / [128](/tpt/fields/128-option-premium-convertible-instrument-only) – bond floor, option premium | Considered for deletion in the consultation; retained and still optional. |
| [1000 – TPT version](/tpt/fields/1000-tpt-version) | `V8.0 (official) dated 8 October 2026`. |

A further 26 fields only had typographical or comment corrections. The Solvency II review changes the SCR
calculation without changing the structure of the SCR fields 97–105b; the values reported there may change.

Every field page shows the definition, flags and codes of V8 and points out where V7 differs. The converter
matches columns by field number, so a file with V7 column names is still read correctly as V8.

## V8 in FundsXML 4

FundsXML 4.2.11 has a Solvency II block for V7 only (`TripartiteTemplateSolvencyII_V7`). The converter therefore
writes V8 files into that block and keeps what the block cannot hold:

- fields 150 and 151,
- the codes e1/e2/e3 of field 56 (the block receives `e`),
- the issuer code type `2` of fields 48, 51, 82 and 85 (the block only knows `1` and `9`),
- the full version label of field 1000,

as custom attributes named `TPT_<field>` on the position or fund. Converting the document back to TPT V8 reads
these attributes first, so the round trip is lossless. The conversion report says so in the message
*"FundsXML 4.2.11 has no TPT V8 block"* — see [conversion messages](/tpt/issues).

The V7 block also requires a few elements V8 no longer maintains. So that the block stays complete for readers
of FundsXML 4.2.11, the converter fills them from the V8 data: the code types 116, 120 and 141 are `1` (V8
requires LEIs in 115, 119 and 140), the fund issuer sector 118 is `K6430` (NACE for collective investment
undertakings), the index name 36 repeats the reference identification 34, and the option direction 44 follows
field 42 (`Cal` → `I`, `Put` → `B`). The issuer code type `2` is written as `9` in the block, with the `2` kept
as custom attribute. None of these values comes back in a V8 output.

FundsXML 4.2.12 will add a dedicated `TripartiteTemplateSolvencyII_V8` block whose element names follow the V8
field names; the field pages already show its path. The converter switches to it once that version is released.

## Converting between V7 and V8

FundsXML → TPT can write either version.

- **Writing V8** from V7 data: the 18 fields V8 no longer maintains stay empty — including the code types 116 and
  120 that V7 required — and field 1000 gets the V8 label. The report lists the values left out
  (*"TPT V8 no longer maintains field(s) …"*). Issuer code types are copied as they are: a V7 `9` stays `9`, since
  the data does not say whether an external identifier exists.
- **Writing V7** from V8 data: fields 150/151 are left out, e1/e2/e3 become `e`, and the code type `2` becomes `9`
  (the V7 code for "not an LEI"). The report lists the adapted values (*"V8 value(s) adapted for TPT V7"*).
