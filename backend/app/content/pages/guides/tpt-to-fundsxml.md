+++
title = "Convert TPT to FundsXML 4: how the mapping works"
heading = "TPT to FundsXML 4"
description = "How a Tripartite Template (TPT V7/V8) file becomes a FundsXML 4.2.11 document: the Solvency II TPT block, funds, share classes, positions and asset master data, and lossless custom attributes."
lastmod = 2026-10-21
cta_label = "Convert TPT to FundsXML"
cta_href = "/"

[[faq]]
q = "Which FundsXML version does the converter write?"
a = "FundsXML 4.2.11. Every document is validated against the bundled XSD, and the report lists any validation error."

[[faq]]
q = "Can I get only the TPT block, or only the core structures?"
a = "Yes. Both are written by default; the options (and the API fields `include_block` and `include_core`) switch either one off."
+++

The converter reads a TPT file (Excel or CSV, V7 or V8) and writes **one FundsXML 4.2.11 document** with two
views of the same data. Both are optional; by default you get both.

## 1. The Solvency II TPT block

`RegulatoryReportings/IndirectReporting/TripartiteTemplateSolvencyII_V7` mirrors the template nearly one to one:
a `Portfolio` per TPT portfolio, with a `Position` per row. Receivers that know the TPT read this block and find
every field where they expect it.

## 2. The FundsXML core structures

The regular FundsXML structures are filled as well, so systems that never look at the regulatory block still get
the holdings:

- **`Funds/Fund/SingleFund/ShareClasses/ShareClass`** — one share class per TPT portfolio, identified by the ISIN
  of field 1, with price (8), net assets (5) and its portfolio.
- **`…/Portfolio/Positions/Position`** — one position per row: identifiers, currency, market value in quotation
  and portfolio currency (22, 24), weight (26), and the quantity or nominal in the element for the instrument
  type (bond, equity, fund share, option, future …).
- **`AssetMasterData/Asset`** — one asset per instrument, with identifiers, name, currency, country and
  `AssetDetails` chosen by the CIC category — for a bond, for example, issuer, maturity and coupon.
- **`ControlData`** — document id, date and data supplier; the supplier can be set in the options.

The fund itself gets only the mandatory name and currency: a TPT describes share classes, not the fund.

## Lossless: custom attributes

Some TPT values have no place in FundsXML 4.2.11 — fields 17b and 114, the V8 fields 150/151, the V8 codes
e1/e2/e3 of field 56 — and the schema rejects others (an over-long name, an unknown code). None of them is
dropped. They are written as

```xml
<CustomAttributes>
  <Attribute><Name>TPT_150</Name><Value>1</Value></Attribute>
</CustomAttributes>
```

on the position (or the fund, for portfolio fields). [FundsXML to TPT](/guides/fundsxml-to-tpt) reads these
attributes first, so TPT → FundsXML → TPT returns the original values; the converter's test suite checks this
for every sample file.

## Field by field

Every field and its FundsXML paths — with the conditions (for example "only for CIC category 2") and
transformations (percentages, basis points) — is listed in the [mapping table](/mapping) and on the
[field pages](/tpt/fields).

## The report

Next to the XML the converter returns a report: XSD validation result, the number of portfolios and positions,
every value that was moved to a custom attribute, and messages such as missing mandatory fields. The
[conversion messages](/tpt/issues) explain each one.
