+++
title = "What is openfunds? The fund data standard and its OF-IDs"
heading = "What is openfunds?"
description = "openfunds is an open standard for exchanging fund data: static data, prices, portfolio holdings and the FinDatEx templates EMT, EPT and EET, each field identified by an OF-ID such as OFST020000."
lastmod = 2026-10-22
cta_label = "Convert an openfunds file"
cta_href = "/openfunds-to-fundsxml"

[[faq]]
q = "Which openfunds version does the converter read?"
a = "openfunds 2.13.0 (March 2026), with all fields of the preceding versions. Revoked fields are reported but kept."

[[faq]]
q = "Can I mix openfunds columns with my own?"
a = "Yes. Columns without an OF-ID are non-openfunds fields (openfunds OFST999990); the converter keeps them under their header name and writes them back unchanged."
+++

**openfunds** is a free, open standard for fund data, maintained by the openfunds association. It does not
define a file format of its own. Instead, it defines **fields**, each with a stable identifier, the **OF-ID**.
The fields are exchanged as columns of an Excel or CSV file: `OFST020000` is the ISIN of a share class, `OFST020540`
its currency, `OFPH000300` the weight of a holding.

## Areas and prefixes

The first four letters of an OF-ID name the area:

| Prefix | Content | Level |
|---|---|---|
| `OFST` | static data: company, umbrella, fund, share class, listing, fees, registrations, tax | one row per share class |
| `OFDY` | dynamic data: NAV, assets under management, number of shares, dividends | one row per share class and date |
| `OFPH` | portfolio holdings: identifiers, CIC, market value, weight, issuer, coupon, maturity | one row per position |
| `OFEM`, `OFEP`, `OFEE`, `OFEF` | the FinDatEx templates EMT (MiFID), EPT (PRIIPs), EET (ESG) and EFT (feedback) | one row per share class |
| `OFRE`, `OFDC`, `OFCA`, … | ratios and breakdowns, pension costs, corporate actions, … | various |

Most holding fields and all template fields name their FinDatEx counterpart. `OFPH000300` *Holding Net Weight as
Percentage*, for example, is the same value as field 26 of the [Tripartite Template](/guides/what-is-tpt). The
converter uses these references to map openfunds to FundsXML and TPT.

## Layout of a file

- **Flat:** the usual form. Each row is a share class, and each column is an OF-ID. Country fields have a
  country code in place of `XX`: `OFST6030AT` is the legal registration in Austria.
- **Narrow:** several rows per share class. `OFST600000` names the country of the `OFST6nnnXX` columns,
  or `OFDY100100`/`OFDY100111` give field and value of dynamic data.
- **Holdings** are a table of their own (a separate sheet or file), one row per position, linked to the
  share class by its ISIN in `OFST020000`.

An empty cell means *unknown*. `[IGNORE]` means *do not overwrite*. Percentages are decimal fractions: 1
stands for 100 %. A header cell may carry a language tag, such as `OFST010110(de)` for a German fund name.

## openfunds and FundsXML

FundsXML 4 describes the same funds, share classes and holdings as XML. The converter translates between the
two. Static data goes into the fund and share class structures. Holdings become positions with asset master
data. The template fields go into the FundsXML EMT, EPT, EET and EFT blocks. Anything FundsXML has no element
for is kept as a custom attribute, so nothing is lost.
See [openfunds to FundsXML](/guides/openfunds-to-fundsxml) and the [openfunds field list](/openfunds/fields).
