"""FundsXML 4 → openfunds share class records and holdings.

Every ``ShareClass`` (or a fund without share classes) becomes one share class record. Sources, in
order of precedence for every column:

1. ``CustomAttributes`` named ``OF_<OF-ID>`` – the exact original value kept by this converter;
2. the static rules (``app.mapping.openfunds_rules``) on the fund and the share class.

Holdings come from the TPT extraction of the same document (``extract_tpt``: TPT block, else the
core portfolios) and are translated into ``OFPH`` columns. The share class is named by
``OFST020000`` (ISIN) or ``OFST020001``/``OFST020002``. If the document carries TPT data (a TPT
block or ``TPT_…`` custom attributes), TPT fields without an openfunds column are added as
non-openfunds columns named ``TPT_<field>`` (optional), so TPT → openfunds → TPT is lossless.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from lxml import etree

from app.convert.to_tpt import BLOCK_PATH, _compiled, _read, extract_tpt
from app.ingest.openfunds_reader import INSTRUMENT_ID, ISIN
from app.mapping.openfunds_holdings import tpt_keys, tpt_to_holding
from app.mapping.openfunds_rules import OF_FUND, OF_SHARECLASS, STATIC_RULES
from app.mapping.openfunds_templates import Template, templates
from app.model.issues import Issue
from app.spec.catalog import load_catalog

CUSTOM_PREFIX = "OF_"
TPT_PREFIX = "TPT_"
# TPT extraction notes that do not concern an openfunds file.
TPT_ONLY_ISSUES = {"no_positions", "mandatory_missing", "older_tpt_block"}
# TPT fields that name the share class of a holding row, not the holding.
TPT_KEYS = ("1", "2")


@dataclass
class OfExtract:
    shareclasses: list[dict[str, str]]
    holdings: list[dict[str, str]]
    issues: list[Issue] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    tpt_origin: bool = False


def extract_openfunds(root: etree._Element, non_openfunds_columns: bool = True) -> OfExtract:
    issues: list[Issue] = []
    fund_rules = [r for r in STATIC_RULES if r.ctx == OF_FUND]
    sc_rules = [r for r in STATIC_RULES if r.ctx == OF_SHARECLASS]
    records: list[dict[str, str]] = []
    for fund in root.iterfind("Funds/Fund"):
        classes = fund.findall("SingleFund/ShareClasses/ShareClass")
        if fund.find("Subfunds") is not None:
            issues.append(
                Issue(
                    "warning",
                    "of_subfunds_skipped",
                    "Umbrella structures (Fund/Subfunds) are not read; only single funds and their "
                    "share classes.",
                )
            )
        for sc in classes or [None]:
            values = _custom_values(sc if sc is not None else fund)
            if sc is not None:
                _read(sc, sc_rules, values)
            _read(fund, fund_rules, values)
            records.append({k: v for k, v in values.items() if v})
    _read_templates(root, records)

    tpt = extract_tpt(root)
    issues += [i for i in tpt.issues if i.code not in TPT_ONLY_ISSUES]
    tpt_origin = root.find(BLOCK_PATH) is not None or _tpt_only_attributes(root)
    catalog = load_catalog(tpt.version)
    holdings: list[dict[str, str]] = []
    for row, pos in zip(tpt.rows, tpt.positions, strict=True):
        values, kept = tpt_to_holding(row)
        out = _shareclass_key(row)
        out.update(values)
        if pos is not None:
            out.update(_custom_values(pos))
        if non_openfunds_columns and tpt_origin:
            for key, value in row.items():
                if key in kept or key in TPT_KEYS or not value:
                    continue
                spec = catalog.by_key.get(key)
                out.setdefault(TPT_PREFIX + (spec.num_data if spec else key), value)
        holdings.append(out)
    stats = {
        "funds": len(root.findall("Funds/Fund")),
        "shareclasses": len(records),
        "positions": len(holdings),
        "source": tpt.source if holdings else "core",
    }
    if not records and not holdings:
        issues.append(Issue("error", "no_shareclasses", "The document contains neither funds nor positions."))
    return OfExtract(records, holdings, issues, stats, tpt_origin)


# Elements that identify the instrument of a template record, besides FundOrShareClassIdentifiers.
TEMPLATE_IDS = (
    "FundOrShareClassIdentifiers/ISINs/ISIN",
    "GeneralInformation/Code",
    "GeneralFinancialInstrumentInformation/IdentifyingData",
    "GeneralPortfolioInformation/PortfolioID/Code",
)


def _read_templates(root: etree._Element, records: list[dict[str, str]]) -> None:
    """Template values into the record of their share class; a record of its own if there is none."""
    by_isin = {r[ISIN].upper(): r for r in records if r.get(ISIN)}
    for tpl in templates():
        for el in root.xpath(tpl.record):
            ids = [(x.text or "").strip().upper() for p in TEMPLATE_IDS for x in el.iterfind(p)]
            record = next((by_isin[i] for i in ids if i in by_isin), None)
            if record is None:
                if not ids or not ids[0]:
                    continue
                record = {ISIN: ids[0]}
                records.append(record)
                by_isin[ids[0]] = record
            _read_template(el, tpl, record)


def _read_template(el: etree._Element, tpl: Template, values: dict[str, str]) -> None:
    for f in tpl.fields:
        if values.get(f.of_id):
            continue
        found = _compiled(f.path)(el)
        texts = [(n if isinstance(n, str) else (n.text or "")).strip() for n in found]
        texts = [t for t in texts if t]
        if texts:
            value = f.from_xml(texts if f.many else texts[:1])
            if value:
                values[f.of_id] = value


def _tpt_only_attributes(root: etree._Element) -> bool:
    """``TPT_…`` custom attributes for a field openfunds has no column for: TPT data, not a fallback."""
    for name in root.xpath("//CustomAttributes/Attribute/Name[starts-with(., 'TPT_')]/text()"):
        if name[len(TPT_PREFIX) :].split("_", 1)[0].lower() not in tpt_keys():
            return True
    return False


def _shareclass_key(row: dict[str, str]) -> dict[str, str]:
    code, kind = row.get("1", ""), row.get("2", "")
    if not code:
        return {}
    if kind == "1":
        return {ISIN: code}
    return {INSTRUMENT_ID: code, "OFST020002": kind} if kind else {INSTRUMENT_ID: code}


def _custom_values(el: etree._Element | None) -> dict[str, str]:
    """``OF_…`` custom attributes: OF-ID columns and non-openfunds columns, by their original name."""
    out: dict[str, str] = {}
    if el is None:
        return out
    for attr in el.iterfind("CustomAttributes/Attribute"):
        name = (attr.findtext("Name") or "").strip()
        if not name.startswith(CUSTOM_PREFIX):
            continue  # TPT_… attributes of a position are read by the TPT extraction
        key = name[len(CUSTOM_PREFIX) :]
        value = next(
            (
                (attr.findtext(v) or "")
                for v in ("ValueText", "ValueNumber", "ValueDate", "ValueBoolean")
                if attr.find(v) is not None
            ),
            None,
        )
        if key and value is not None:
            out[key] = value
    return out
