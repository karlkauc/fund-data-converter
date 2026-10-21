+++
title = "Convert FundsXML to TPT: share classes, sources and derived fields"
heading = "FundsXML 4 to TPT"
description = "How the converter builds a Tripartite Template (TPT V7/V8, Excel or CSV) from a FundsXML 4 document: one portfolio per share class, the order of sources, and the fields it derives."
lastmod = 2026-10-21
cta_label = "Convert FundsXML to TPT"
cta_href = "/fundsxml-to-tpt"

[[faq]]
q = "Does the FundsXML document need a TPT block?"
a = "No. Without a TPT block the converter builds the TPT from the fund, share class, position and asset structures and derives what FundsXML only implies."

[[faq]]
q = "Why does every share class get the same positions?"
a = "When the share classes have no portfolio of their own, the fund portfolio is the only one there is. TPT is reported per share class, so that portfolio is repeated for each of them with the share class's own ISIN, NAV and price."
+++

The converter turns a FundsXML 4 document into a TPT file — **Excel (XLSX) or CSV**, **V7 or V8**, with every
TPT column or only the filled ones.

## Where each value comes from

For every field the converter takes the first value it finds, in this order:

1. **Custom attributes** named `TPT_<field>` — the exact original value, as written by
   [TPT to FundsXML](/guides/tpt-to-fundsxml) or anyone following the same convention.
2. **The Solvency II TPT block** `TripartiteTemplateSolvencyII_V7`.
3. **The core structures** — fund, share class, NAV, position and the referenced asset.

Older blocks (`…_V5`, `…_V6`) are not read; the report says so.

## One TPT portfolio per share class

TPT is reported per share class: field 1 holds the share class ISIN, never the fund's. Without a TPT block:

- A share class with its own `Portfolios/Portfolio` uses it.
- Otherwise the fund portfolio from `FundDynamicData` is repeated for each share class, with the share class's
  ISIN, net assets and price.
- The fund portfolio is never a TPT portfolio of its own; only a fund without share classes is reported on fund
  level.
- Share classes without net assets on the valuation date are skipped and listed in the report.

## Derived fields

FundsXML does not carry some TPT fields as such but implies them. When the document leaves them empty, the
converter fills them — never overriding a value that is there:

| Field | Derived as |
|---|---|
| [8b](/tpt/fields/8b-total-number-of-shares) shares outstanding | net assets (5) / share price (8) |
| [9](/tpt/fields/9-cash-ratio) cash ratio | sum of the weights (26) of cash positions (CIC xx7x) |
| [11](/tpt/fields/11-complete-scr-delivery) complete SCR delivery | `N` when no SCR contribution (97–105b) is given |
| 23 / 25 clean value | market value minus accrued interest; equal to it for instruments without interest |
| 27 / 28 / 30 market exposure | commitment value for derivatives, market value otherwise |
| [46](/tpt/fields/46-issuer-name) / [49](/tpt/fields/49-name-of-the-group-of-the-issuer) issuer and group name | instrument name (17), as a last resort |
| 48 / 51 / 116 / 120 code types | `9` (none) when no LEI is given |
| [117](/tpt/fields/117-fund-issuer-name) / [122](/tpt/fields/122-fund-issuer-country) fund issuer | investment company in `FundStaticData`, else the data supplier in `ControlData` |
| 131 underlying asset category | from the CIC code |

Market values in portfolio currency (24) that are missing are converted from the fund currency at the rate the
share class NAV implies; the report says when that happened.

## Output options

- **XLSX** with one sheet, or **CSV** separated by semicolon (default), comma, pipe or tab — UTF-8 with BOM.
- **All columns** (default) or only the columns that hold a value.
- **V7 or V8.** V8-only values kept as custom attributes are written to V8 and reported as lost for V7.
