+++
title = "Convert FundsXML 4 to openfunds (Excel or CSV)"
heading = "FundsXML 4 to openfunds"
description = "How a FundsXML 4 document becomes an openfunds file: one row per share class with OF-ID columns, a holdings sheet with OFPH columns, template fields from the EMT/EPT/EET/EFT blocks."
lastmod = 2026-10-22
cta_label = "Convert FundsXML to openfunds"
cta_href = "/fundsxml-to-openfunds"

[[faq]]
q = "Why is the CSV output a ZIP file?"
a = "openfunds share class data and holdings are two tables. As XLSX they are two sheets of one file; as CSV they are two files, delivered in one ZIP. Without holdings the CSV comes as a single file."

[[faq]]
q = "Can I get every openfunds column, even empty ones?"
a = "Yes: the API field all_columns=true writes every static data and holding column. By default only filled columns are written."
+++

The converter reads a FundsXML 4 document and writes an **openfunds file**. As XLSX, it has the sheets
`openfunds` (one row per share class) and `Holdings` (one row per position). As CSV, the two tables come as
two files in one ZIP. The header row holds the OF-IDs. An option adds a second header row with the field names.

## Share classes

Every `ShareClass` becomes a row. A fund without share classes becomes a row of its own. The columns come from:

1. **custom attributes** `OF_<OF-ID>` — the exact original values kept by
   [openfunds to FundsXML](/guides/openfunds-to-fundsxml);
2. the fund and share class structures: identifiers, names, currency, static data, prices, assets, dividends,
   registrations, service providers;
3. the template blocks `EMT_V4_3`, `PRIIPS_V20`, `EET1.1.3` and `EFTs`, matched to the share class by its ISIN.
   A template record without a share class becomes a row of its own.

## Holdings

The holdings are read like a FundsXML → TPT conversion. The converter takes the share class portfolios, or the
fund portfolio repeated for each share class, or the TPT block. It then translates them into `OFPH` columns:
identifiers, CIC, market values, weight, quantity, issuer, coupon, maturity, underlying. `OFST020000` links
each holding to its share class.

If the document comes from a TPT file (it has a TPT block or `TPT_` custom attributes), the holdings sheet also
gets the TPT fields openfunds has no column for, as non-openfunds columns `TPT_<field>`. With them,
[TPT to openfunds](/guides/tpt-to-openfunds) and back is lossless.

Columns follow the openfunds field order. Columns without an OF-ID (`OFST999990` non-openfunds fields) come last.
