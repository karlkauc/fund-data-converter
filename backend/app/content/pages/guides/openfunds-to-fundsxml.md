+++
title = "Convert openfunds to FundsXML 4: static data, holdings and templates"
heading = "openfunds to FundsXML 4"
description = "How an openfunds file becomes a FundsXML 4.2.11 document: share class and fund static data, NAVs, OFPH holdings as positions, EMT/EPT/EET/EFT template blocks and lossless custom attributes."
lastmod = 2026-10-22
cta_label = "Convert openfunds to FundsXML"
cta_href = "/openfunds-to-fundsxml"

[[faq]]
q = "What happens to openfunds fields FundsXML has no element for?"
a = "They are written as custom attributes named OF_<OF-ID> on the share class (or position). FundsXML to openfunds reads them first, so the round trip returns the original file."

[[faq]]
q = "Which file formats are accepted?"
a = "XLSX (all sheets are read; a sheet of OFPH columns holds the holdings), CSV with any common delimiter, and a ZIP of such files. Flat and narrow layouts are detected automatically."
+++

The converter reads an openfunds file (XLSX, CSV or a ZIP of both) and writes **one FundsXML 4.2.11 document**,
validated against the bundled schema. The [openfunds field list](/openfunds/fields) shows the target of every
single field.

## Funds and share classes

Share class rows are grouped into funds by the fund's LEI (`OFST010030`), or else by the legal fund name
(`OFST010020`). Each fund becomes a `Funds/Fund` with its share classes. Fund-level values are written once,
from the fund's first share class. A share class whose value differs keeps that value as a custom attribute.

- **Share class:** identifiers (ISIN, WKN, Valor, CUSIP, SEDOL, FIGI, Bloomberg …), names, currency, share
  class type and distribution policy, launch date, hedging, minimum investment, fees, transfer agent,
  registration countries, listings.
- **Fund:** names, currency, LEI and regulator codes, domicile, legal structure, launch date, fiscal year,
  management company, custodian, auditor, administrator and the other service providers, classifications,
  portfolio managers, tracked index.
- **Dynamic data:** the valuation NAV goes to `Prices/Price`, assets under management and number of shares
  to `TotalAssetValues`, and dividends to `Distributions`.

## Holdings

`OFPH` rows become `Portfolio/Positions/Position` elements of their share class (`OFST020000`), plus one
`AssetMasterData/Asset` per instrument. openfunds documents the TPT field of each holding field, so the converter
translates a holding into TPT values and writes it with the same rules as a [TPT file](/guides/tpt-to-fundsxml):
CIC, market values, weight, quantity or nominal, issuer, coupon, maturity, underlying.

## Templates: EMT, EPT, EET, EFT

The `OFEM`, `OFEP`, `OFEE` and `OFEF` fields name their FinDatEx field (for example `EMT: 00001_EMT_Version`).
FundsXML documents the same numbers in its template blocks `EMT_V4_3`, `PRIIPS_V20`, `EET1.1.3` and `EFTs`, so
about 880 template fields have an exact target. Yes/no values become `Y`/`N` or `YES`/`NO`, and decimal
fractions become FundsXML percentages. A template block needs its mandatory fields. If they are missing, the
block is not written, its values are kept as custom attributes and the report says so (`of_template_incomplete`).

## Lossless: custom attributes

Every value that does not reach a FundsXML element is kept:

```xml
<CustomAttributes>
  <Attribute><Name>OF_OFST500010</Name><Type>T</Type><ValueText>yes</ValueText></Attribute>
</CustomAttributes>
```

These are fields without a FundsXML counterpart, values the schema rejects and values a code list cannot
express exactly. [FundsXML to openfunds](/guides/fundsxml-to-openfunds) reads them first, so openfunds →
FundsXML → openfunds returns every value; the converter's tests check this.
