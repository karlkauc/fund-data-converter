+++
title = "What is the Tripartite Template (TPT)?"
heading = "What is the Tripartite Template (TPT)?"
description = "The FinDatEx Tripartite Template explained: why insurers need fund look-through data for Solvency II, what a TPT file contains and how it relates to FundsXML."
lastmod = 2026-10-21
cta_label = "Convert a TPT file"
cta_href = "/"

[[faq]]
q = "Who maintains the Tripartite Template?"
a = "FinDatEx (Financial Data Exchange Templates), the joint initiative of European asset management, insurance and distribution associations. It publishes the template, its field definitions and change logs."

[[faq]]
q = "Is TPT the same as FundsXML?"
a = "No. TPT is a flat table with one row per position. FundsXML is an XML standard for all kinds of fund data; since version 4 it has a Solvency II TPT block, so a TPT can travel inside a FundsXML document."
+++

The **Tripartite Template (TPT)** is the standard file in which fund managers give insurance companies the
holdings of their funds. Insurers need these *look-through* data for **Solvency II**: the capital requirement
(SCR) and the quantitative reporting templates have to account for what a fund actually holds, not just for the
fund units.

## What a TPT file contains

A TPT is a table — usually Excel or CSV — with **one row per position** of a portfolio and one column per field.
Version 8 has 154 fields, numbered from 1 to 151 plus some lettered fields (8b, 17b, 105a …) and field 1000 for
the template version. They fall into groups:

- **Portfolio data** (fields 1–11): the share class ISIN, name, currency, net assets, valuation date, price,
  cash ratio. They repeat on every row of the portfolio.
- **Position data** (12–96): instrument identification, the [CIC code](/tpt/fields/12-cic-code-of-the-instrument),
  quantities, market values in quotation and portfolio currency, interest rate characteristics, derivative
  underlyings, issuer and group data, ratings.
- **SCR contributions** (97–105b): the position's contribution to the Solvency II market risk sub-modules as a
  weight of the net assets, if the manager calculates them.
- **QRT information** (106–126): data the insurer needs for its quantitative reporting templates — collateral,
  custody, rating, and the fund itself as an issuer (115–126).
- **Additional information** (127–151): convertible details, yields, private equity and infrastructure flags,
  NACE sector, and the fields added in V8.

[All TPT fields](/tpt/fields) lists every field with its definition, codes and where it applies.

## Flags: mandatory, conditional, optional

Each field carries a flag per regulation: **M** (mandatory), **C** (conditional — required for certain CIC
categories or when another field has a value), **O** (optional) and **I** (indicative). The CIC category of a
position decides which conditional fields it must fill: a bond needs coupon and maturity, a derivative needs
its underlying.

## Versions

FinDatEx revises the template every few years. This converter supports the two current versions:

- **TPT V7** — the official version dated 25 November 2024.
- **TPT V8** — the official version dated 8 October 2026 (published 28 October 2026), mandatory from the
  end-of-March 2027 production: adds fields 150/151, makes issuer identification mandatory, retires 18 fields and
  splits securitisation code e into e1–e3.

[TPT V7 vs V8](/guides/tpt-v7-vs-v8) lists the differences.

## TPT and FundsXML

[FundsXML](https://www.fundsxml.org/) is an open XML standard for exchanging fund data. FundsXML 4 contains a
Solvency II block (`TripartiteTemplateSolvencyII_V7`) that mirrors the template, next to its regular structures
for funds, share classes, portfolios and assets. A TPT can therefore be delivered as a FundsXML document — and
this converter turns one into the other, see [TPT to FundsXML](/guides/tpt-to-fundsxml).
