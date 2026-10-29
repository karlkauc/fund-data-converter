"""One content page per TPT field (``/tpt/fields/12-cic-code-of-the-instrument``) plus the
``/tpt/fields`` table, built from the bundled field catalogs and the mapping rules.

People search for single fields ("TPT field 12", "TPT 24 market valuation"); each page
answers with the definition, the codes, where the field applies and where the converter
puts it in FundsXML 4.
"""

from __future__ import annotations

import json
import re

from app.api.mapping import mapping_table
from app.content.pages import Page
from app.spec.catalog import SPEC_DIR, VERSIONS

HUB = "tpt/fields"

_FLAGS = {
    "M": "Mandatory",
    "C": "Conditional",
    "O": "Optional",
    "I": "Indicative",
    "NA": "Not applicable (no longer maintained, must be empty)",
}
_REGIMES = (
    ("SOLVENCY_II", "Solvency II"),
    ("SST", "Swiss Solvency Test (SST)"),
    ("IORP_EIOPA_ECB", "IORP / EIOPA / ECB"),
    ("NW_675", "NW 675"),
)
_KINDS = {
    "NUMERIC": "Number",
    "FREE_TEXT": "Free text",
    "CLOSED_LIST": "Code from a closed list",
    "DATE": "Date (YYYY-MM-DD)",
    "ALPHANUMERIC": "Alphanumeric code",
    "ALPHA": "Letters",
    "ISO_3166_A2": "ISO 3166-1 alpha-2 country code",
    "ISO_4217": "ISO 4217 currency code",
    "CIC": "CIC code (Complementary Identification Code)",
    "NACE": "NACE code",
}
_CIC = {
    "0": "Other investments",
    "1": "Government bonds",
    "2": "Corporate bonds",
    "3": "Equity",
    "4": "Collective investment undertakings",
    "5": "Structured notes",
    "6": "Collateralised securities",
    "7": "Cash and deposits",
    "8": "Mortgages and loans",
    "9": "Property",
    "A": "Futures",
    "B": "Call options",
    "C": "Put options",
    "D": "Swaps",
    "E": "Forwards",
    "F": "Credit derivatives",
}
_MD_SPECIAL = re.compile(r"([\\`*_\[\]()<>|#])")


def _md(text: str) -> str:
    """Catalog text as literal Markdown (no emphasis, no table breaks, no "(C)" → "©")."""
    return _MD_SPECIAL.sub(r"\\\1", " ".join(text.split()))


def _name(num_data: str) -> str:
    """``12_CIC_code_of_the_instrument`` → ``CIC code of the instrument``."""
    return num_data.split("_", 1)[-1].replace("_", " ").strip()


def _slug(key: str, num_data: str) -> str:
    words = re.sub(r"[^a-z0-9]+", "-", _name(num_data).lower()).strip("-")
    return f"{HUB}/{key}-{words}"


def _raw(version: str) -> dict[str, dict]:
    data = json.loads((SPEC_DIR / f"tpt_{version.lower()}.json").read_text(encoding="utf-8"))
    return {f["numKey"].lower(): f for f in data["fields"]}


def _cic(codes: list[str]) -> str:
    cats = [c.removeprefix("CIC") for c in codes]
    if len(cats) == len(_CIC):
        return "All positions (CIC categories 0–9 and A–F)."
    return "Positions with CIC category " + ", ".join(f"{c} – {_CIC.get(c, c)}" for c in cats) + "."


def _mapping_lines(entry: dict, key: str) -> list[str]:
    def rows(rules: list[dict]) -> list[str]:
        out = []
        for r in rules:
            notes = [n for n in (r.get("when"), r.get("transform")) if n]
            suffix = f" — {_md('; '.join(notes))}" if notes else ""
            out.append(f"- `{r['path']}`{suffix}")
        return out

    lines: list[str] = []
    if entry["block"]:
        lines += ["**Solvency II TPT block** (`TripartiteTemplateSolvencyII_V7`):", ""]
        lines += [*rows(entry["block"]), ""]
    if entry["core"]:
        lines += ["**FundsXML core structures** (fund, position, asset master data):", ""]
        lines += [*rows(entry["core"]), ""]
    if "{" in "".join(r["path"] for r in entry["block"] + entry["core"]):
        lines += ["A field number in braces, such as `{4}`, stands for that field's value in the row.", ""]
    if not lines:
        lines = [
            "FundsXML 4.2.11 has no element for this field. The converter keeps the value as "
            f"`Position/CustomAttributes/Attribute` named `TPT_{key}`, so FundsXML → TPT restores "
            "it unchanged.",
            "",
        ]
    return lines


def field_pages() -> list[Page]:
    raw = {v: _raw(v) for v in VERSIONS}
    tables = {v: {f["key"]: f for f in mapping_table(v)["fields"]} for v in VERSIONS}
    latest = VERSIONS[-1]
    keys = list(tables[latest])
    pages: list[Page] = []
    for i, key in enumerate(keys):
        spec = raw[latest][key]
        entry = tables[latest][key]
        name = _name(spec["numData"])
        versions = [v for v in VERSIONS if key in raw[v]]
        cod = spec.get("codification") or {}
        definition = " ".join((spec.get("definition") or "").split()) or name
        flag = (spec.get("flags") or {}).get("SOLVENCY_II", "")
        flag_text = _FLAGS.get(flag, "not stated")

        lead = _md(definition)
        if definition.lower() != name.lower():
            lead = f"**{_md(name)}:** {lead}"
        body = [
            lead,
            "",
            "| Property | Value |",
            "|---|---|",
            f"| Field number | {key} |",
            f"| Column name | `{spec['numData']}` |",
            f"| TPT versions | {', '.join(versions)} |",
            f"| Format | {_KINDS.get(cod.get('kind', ''), 'Not specified')} |",
        ]
        if cod.get("maxLength"):
            body.append(f"| Maximum length | {cod['maxLength']} |")
        if (spec.get("fundXmlPath") or "").startswith(("Portfolio", "Position")):
            body.append(f"| FinDatEx path in the FundsXML TPT block | {_md(spec['fundXmlPath'])} |")
        for regime, label in _REGIMES:
            value = (spec.get("flags") or {}).get(regime)
            if value in _FLAGS:
                body.append(f"| {label} | {_FLAGS[value]} (`{value}`) |")  # a bare (C) would turn into ©
        body.append("")

        codes = cod.get("closedList") or []
        if any(c["label"] != c["code"] for c in codes):
            body += ["## Allowed codes", "", "| Code | Meaning |", "|---|---|"]
            body += [f"| {_md(c['code'])} | {_md(c['label'])} |" for c in codes]
            body.append("")
        elif codes:
            body += ["## Allowed codes", "", ", ".join(f"`{c['code']}`" for c in codes), ""]
        if spec.get("applicableCic"):
            body += ["## Applies to", "", _cic(spec["applicableCic"]), ""]

        # Differences between the template versions, as the catalogs state them.
        changes = []
        for v in VERSIONS[:-1]:
            old = raw[v].get(key)
            if old is None:
                changes.append(f"New in TPT {latest}; TPT {v} has no field {key}.")
                continue
            old_flag = (old.get("flags") or {}).get("SOLVENCY_II", "")
            if flag == "NA" and old_flag != "NA":
                changes.append(
                    f"No longer maintained in TPT {latest}: the column stays but must be left empty "
                    f"(TPT {v}: {_FLAGS.get(old_flag, 'not stated').lower()})."
                )
            elif flag != old_flag and flag in _FLAGS and old_flag in _FLAGS:
                changes.append(
                    f"Solvency II flag in TPT {latest}: {_FLAGS[flag]} (TPT {v}: {_FLAGS[old_flag]})."
                )
            if old["numData"] != spec["numData"]:
                changes.append(f"Renamed in TPT {latest}; the TPT {v} column is `{old['numData']}`.")
            if flag == "NA":
                continue  # definition and codes are blank in the catalog
            if old.get("codification") != spec.get("codification"):
                old_codes = {c["code"] for c in (old.get("codification") or {}).get("closedList", [])}
                added = [c["code"] for c in cod.get("closedList", []) if c["code"] not in old_codes]
                what = f"codes {', '.join(added)} added" if added else "codification changed"
                changes.append(f"TPT {latest} vs {v}: {what}.")
            elif " ".join((old.get("definition") or "").split()) != definition:
                changes.append(f"TPT {v} definition: “{_md(' '.join(old['definition'].split()))}”.")
        if changes:
            body += ["## Version differences", "", *[f"- {c}" for c in changes], ""]

        body += ["## FundsXML 4 mapping", ""]
        body += _mapping_lines(entry, key)
        body += [
            "The [field mapping table](/mapping) lists every field side by side; "
            "[TPT to FundsXML](/guides/tpt-to-fundsxml) explains the rules behind it.",
            "",
        ]

        nav = []
        if i > 0:
            prev = keys[i - 1]
            nav.append(f"← [Field {prev}](/{_slug(prev, raw[latest][prev]['numData'])})")
        nav.append(f"[All TPT fields](/{HUB})")
        if i + 1 < len(keys):
            nxt = keys[i + 1]
            nav.append(f"[Field {nxt}](/{_slug(nxt, raw[latest][nxt]['numData'])}) →")
        body.append(" · ".join(nav))

        short = definition if len(definition) <= 80 else definition[:77].rsplit(" ", 1)[0] + "…"
        short = short.rstrip(" .") + ("" if short.endswith("…") else ".")
        pages.append(
            Page(
                slug=_slug(key, spec["numData"]),
                title=f"TPT field {key}: {name}",
                heading=f"TPT field {key} – {name}",
                description=(
                    f"TPT field {key}, {name}: {short} Solvency II: {flag_text.lower()}. "
                    "Format, codes, FundsXML 4 mapping."
                ),
                body="\n".join(body),
                cta_label="Convert a TPT file",
                cta_href="/",
            )
        )
    pages.append(_hub(keys, raw[latest], tables[latest]))
    return pages


def _hub(keys: list[str], raw: dict[str, dict], table: dict[str, dict]) -> Page:
    where = {"block+core": "Block + core", "block": "TPT block", "core": "Core", "custom": "Custom attribute"}
    rows = ["| Field | Name | Solvency II | In FundsXML |", "|---|---|---|---|"]
    for key in keys:
        spec = raw[key]
        flag = (spec.get("flags") or {}).get("SOLVENCY_II", "")
        rows.append(
            f"| {key} | [{_md(_name(spec['numData']))}](/{_slug(key, spec['numData'])}) "
            f"| {flag if flag in _FLAGS else ''} | {where[table[key]['status']]} |"
        )
    body = [
        f"The FinDatEx Tripartite Template {VERSIONS[-1]} has {len(keys)} fields. Each page below gives the "
        "definition, the format and allowed codes, the CIC categories it applies to and where the "
        "Fund Data Converter puts the value in FundsXML 4.",
        "",
        "Solvency II flags: **M** mandatory, **C** conditional, **O** optional, **I** indicative, "
        "**NA** retained in V8 but no longer maintained (must be empty). "
        "*TPT block* means the Solvency II block `TripartiteTemplateSolvencyII_V7`, *core* the regular "
        "FundsXML fund, position and asset structures.",
        "",
        *rows,
    ]
    return Page(
        slug=HUB,
        title="All TPT fields: Tripartite Template V7 and V8 field list",
        heading="Tripartite Template (TPT) fields",
        description=(
            f"All {len(keys)} fields of the FinDatEx Tripartite Template V7 and V8 with Solvency II flag, "
            "format, allowed codes and their FundsXML 4 mapping."
        ),
        body="\n".join(body),
        cta_label="Convert a TPT file",
        cta_href="/",
    )
