"""One content page per openfunds field (``/openfunds/fields/ofst020000-isin``) plus the
``/openfunds/fields`` table, built from the openfunds field catalog and the mapping rules.

People search for single OF-IDs ("OFST020000", "OFPH000300 openfunds"); each page answers with the
openfunds definition, the format and values, the FinDatEx template field it corresponds to and where
the converter puts it in FundsXML 4.
"""

from __future__ import annotations

import re

from app.api.mapping import openfunds_mapping_table
from app.content.fields import _md
from app.content.pages import Page
from app.spec.openfunds import load_openfunds

HUB = "openfunds/fields"
OPENFUNDS_URL = "https://www.openfunds.org/fields/fieldlist.htm"
_TYPES = {
    "string": "Text",
    "double": "Decimal number",
    "integer": "Integer",
    "boolean": "yes / no",
    "date": "Date (YYYY-MM-DD)",
    "time": "Time (hh:mm)",
}
_PREFIXES = {
    "OFST": "Static data",
    "OFDY": "Dynamic data (prices, assets, dividends)",
    "OFPH": "Portfolio holdings",
    "OFEM": "European MiFID Template (EMT)",
    "OFEP": "European PRIIPs Template (EPT)",
    "OFEE": "European ESG Template (EET)",
    "OFEF": "European Feedback Template (EFT)",
    "OFRE": "Fund ratios and exposures",
    "OFDC": "Defined contribution pensions (DCPT)",
    "OFCA": "Corporate actions",
    "OFNW": "News",
    "OFPM": "Portfolio managers",
    "OFFV": "Fair value",
    "OFIN": "Investors",
}
_STATUS = {
    "core": "FundsXML core structures",
    "template": "FundsXML template block",
    "holding": "Position (via the TPT fields)",
    "custom": "Custom attribute",
}


def _slug(of_id: str, name: str) -> str:
    words = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return f"{HUB}/{of_id.lower()}-{words}"


def _paragraphs(text: str) -> list[str]:
    """Catalog text as Markdown paragraphs."""
    return [_md(p) for p in text.split("\n\n") if p.strip()]


def _mapping_lines(entry: dict) -> list[str]:
    def rows(rules: list[dict]) -> list[str]:
        out = []
        for r in rules:
            notes = [n for n in (r.get("when"), r.get("transform")) if n]
            suffix = f" — {_md('; '.join(notes))}" if notes else ""
            out.append(f"- `{r['path']}`{suffix}")
        return out

    if entry["status"] == "core":
        lines = ["**FundsXML core structures:**", "", *rows(entry["core"]), ""]
        if "{" in "".join(r["path"] for r in entry["core"]):
            lines += ["An OF-ID in braces, such as `{OFST020540}`, stands for that field's value.", ""]
        return lines
    if entry["status"] == "template":
        template = entry["template"][0]["template"]
        return [f"**FundsXML {template} block:**", "", *rows(entry["template"]), ""]
    if entry["status"] == "holding":
        fields = ", ".join(entry["holding"])
        return [
            f"The holding value becomes TPT field {fields} and is written like a TPT position: "
            "`Fund/…/Portfolio/Positions/Position` and `AssetMasterData/Asset` (see the "
            "[TPT field pages](/tpt/fields)).",
            "",
        ]
    return [
        "FundsXML 4.2.11 has no element for this field. The converter keeps the value as "
        f"`CustomAttributes/Attribute` named `OF_{entry['key']}` on the share class (or position), so "
        "FundsXML → openfunds restores it unchanged.",
        "",
    ]


def openfunds_field_pages() -> list[Page]:
    catalog = load_openfunds()
    table = {f["key"]: f for f in openfunds_mapping_table()["fields"]}
    keys = list(table)
    pages: list[Page] = []
    for i, key in enumerate(keys):
        f = catalog.by_id[key]
        entry = table[key]
        body = [
            *[p + "\n" for p in _paragraphs(f.description) or [_md(f.name)]],
            "| Property | Value |",
            "|---|---|",
            f"| OF-ID | `{key}` |",
            f"| Name | {_md(f.name)} |",
            f"| Area | {_PREFIXES.get(f.prefix, f.prefix)} |",
            f"| Level | {_md(f.level)} |",
            f"| Format | {_TYPES.get(f.data_type, f.data_type)} |",
        ]
        if f.tags:
            body.append(f"| Tags | {_md(', '.join(f.tags))} |")
        if f.introduced:
            body.append(f"| Introduced in | openfunds {f.introduced} |")
        for ref in f.findatex:
            body.append(f"| FinDatEx {ref.template} field | `{ref.name}` |")
        if f.link and f.link in keys:
            linked = catalog.by_id[f.link]
            body.append(f"| Related field | [{f.link} {_md(linked.name)}](/{_slug(f.link, linked.name)}) |")
        body.append("")
        if f.codes:
            body += ["## Allowed values", "", ", ".join(f"`{c}`" for c in f.codes), ""]
        elif f.values.strip():
            body += ["## Values", "", *_paragraphs(f.values), ""]
        if f.example.strip():
            body += ["## Example", "", f"`{f.example.strip()}`", ""]
        if f.country_pattern:
            body += [
                "## Country columns",
                "",
                f"`XX` stands for an ISO 3166 country code: `{key[:-2]}AT` is the column for Austria. In "
                "the narrow layout the country is given in `OFST600000` instead.",
                "",
            ]
        body += ["## FundsXML 4 mapping", "", *_mapping_lines(entry)]
        body += [
            "The [field mapping table](/mapping) lists every field; "
            "[openfunds to FundsXML](/guides/openfunds-to-fundsxml) explains the rules behind it.",
            "",
        ]
        nav = []
        if i > 0:
            prev = keys[i - 1]
            nav.append(f"← [{prev}](/{_slug(prev, catalog.by_id[prev].name)})")
        nav.append(f"[All openfunds fields](/{HUB})")
        if i + 1 < len(keys):
            nxt = keys[i + 1]
            nav.append(f"[{nxt}](/{_slug(nxt, catalog.by_id[nxt].name)}) →")
        body.append(" · ".join(nav))

        lead = " ".join(f.description.split()) or f.name
        short = lead if len(lead) <= 90 else lead[:87].rsplit(" ", 1)[0] + "…"
        pages.append(
            Page(
                slug=_slug(key, f.name),
                title=f"openfunds {key}: {f.name}",
                heading=f"{key} – {f.name}",
                description=f"openfunds {key} ({f.name}): {short} Format, values and FundsXML 4 mapping.",
                body="\n".join(body),
                cta_label="Convert an openfunds file",
                cta_href="/openfunds-to-fundsxml",
            )
        )
    pages.append(_hub(keys, table))
    return pages


def _hub(keys: list[str], table: dict[str, dict]) -> Page:
    catalog = load_openfunds()
    body = [
        f"openfunds {catalog.version} ({catalog.date}) has {len(keys)} active fields. Each page below gives "
        "the openfunds definition, the format and values, the FinDatEx template field where there is one, "
        "and where the TPT ⇄ FundsXML Converter puts the value in FundsXML 4. Fields without a FundsXML "
        "counterpart are kept as custom attributes `OF_<OF-ID>`, so nothing is lost. Source: the "
        f"[openfunds field list]({OPENFUNDS_URL}).",
        "",
    ]
    for prefix, title in _PREFIXES.items():
        members = [k for k in keys if k.startswith(prefix)]
        if not members:
            continue
        body += [f"## {title} ({prefix})", "", "| OF-ID | Name | Level | In FundsXML |", "|---|---|---|---|"]
        for key in members:
            f = catalog.by_id[key]
            body.append(
                f"| {key} | [{_md(f.name)}](/{_slug(key, f.name)}) | {_md(f.level)} "
                f"| {_STATUS[table[key]['status']]} |"
            )
        body.append("")
    return Page(
        slug=HUB,
        title=f"All openfunds fields: openfunds {catalog.version} field list with FundsXML mapping",
        heading="openfunds fields",
        description=(
            f"All {len(keys)} fields of openfunds {catalog.version} — static data, holdings, EMT, EPT, EET "
            "and more — with format, values and their FundsXML 4 mapping."
        ),
        body="\n".join(body),
        cta_label="Convert an openfunds file",
        cta_href="/openfunds-to-fundsxml",
    )
