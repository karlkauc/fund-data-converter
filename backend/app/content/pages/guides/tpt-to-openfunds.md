+++
title = "Convert TPT to openfunds and back: Tripartite Template ⇄ OFPH holdings"
heading = "TPT ⇄ openfunds"
description = "How a Solvency II Tripartite Template (V7/V8) becomes an openfunds file with OFPH holdings, and back: the FundsXML step, the fields both know, and how every TPT field is kept."
lastmod = 2026-10-22
cta_label = "Convert TPT to openfunds"
cta_href = "/tpt-to-openfunds"

[[faq]]
q = "Is TPT → openfunds → TPT lossless?"
a = "Yes, with the default option non_openfunds_columns: TPT fields without an openfunds column travel as columns TPT_<field>. The converter's tests run every sample file through this round trip."

[[faq]]
q = "What does openfunds → TPT leave out?"
a = "Everything a TPT has no field for: most static data (domicile, fees, registrations, …) and the EMT/EPT/EET fields. The report lists these columns (hop_data_loss)."
+++

openfunds documents the TPT field of most of its holding fields. `OFPH000215` *Holding CIC* is TPT field 12,
for example, and `OFPH000300` *Holding Net Weight as Percentage* is field 26. The converter goes **through
FundsXML 4**: TPT → FundsXML → openfunds, and back. Both steps are the regular conversions, with the same rules
and the same report.

## What maps to what

| TPT | openfunds |
|---|---|
| 1, 2 portfolio id and type | `OFST020000` ISIN (or `OFST020001`/`OFST020002`) |
| 3, 4, 5, 6, 8, 8b name, currency, net assets, date, price, shares | share class row: `OFST020060`, `OFST020540`, `OFDY000070`, `OFDY000071`, `OFDY000035`, `OFDY000075` |
| 14, 15 instrument id and type | `OFPH000100` ISIN, `OFPH000110` WKN, `OFPH000145` CUSIP, … by the type in 15 |
| 12, 17, 21, 22, 24, 26 … | `OFPH000215`, `OFPH000200`, `OFPH000400`, `OFPH000255`, `OFPH000250`, `OFPH000300` … |
| 47, 48 = 1 issuer LEI | `OFPH000710` |
| 32, 38, 40, 42, 44, 58, 64 | same meaning, other spelling: `Floating`, `quarterly`, `bullet`, `Call`, `issuer`, `yes`, `European` |

The [openfunds field list](/openfunds/fields) shows the TPT field of every holding column.

## TPT → openfunds

The converter writes the share class row and one holding row per TPT position. TPT fields without an openfunds
column are kept as **non-openfunds columns** `TPT_<field>` in the holdings sheet. Examples are the SCR
contributions, the Solvency II exposure fields and the fund issuer data. So the openfunds file still carries the
whole TPT. Switch the option off (`non_openfunds_columns=false`) for a pure openfunds file; the report then lists
the TPT fields that were dropped.

## openfunds → TPT

Each share class with holdings becomes a TPT portfolio. A TPT has fields for the holdings and a few share class
values only. All other openfunds columns cannot be carried: domicile, fees, registrations and the template
fields. The report names them (`hop_data_loss`). If the file has `TPT_` columns, they restore the TPT exactly.
