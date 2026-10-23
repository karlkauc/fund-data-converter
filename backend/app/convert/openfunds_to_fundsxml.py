"""openfunds → FundsXML 4.

Share class records are grouped into funds (by fund LEI, else legal fund name). Each fund becomes a
``Funds/Fund`` with its share classes; fund-level values are written once, from the fund's first
share class. Holdings (``OFPH``) are translated into TPT position values
(``app.mapping.openfunds_holdings``) and written with the TPT core rules as
``ShareClass/Portfolios/Portfolio/Positions/Position`` plus ``AssetMasterData/Asset``.

Values that end up nowhere – fields without a FundsXML counterpart, values the schema rejects,
values a transform cannot represent exactly – are kept as ``CustomAttributes`` named
``OF_<OF-ID>`` on the share class (or position), so the reverse conversion restores the original
file. Non-openfunds columns keep their header (``OF_<header>``); a ``TPT_…`` column is kept as is,
which lets a TPT file travel through openfunds without loss.
"""

from __future__ import annotations

import re
import uuid
from collections import Counter, OrderedDict
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime

from lxml import etree

from app.convert.derive import DERIVED_FIELDS
from app.convert.to_fundsxml import (
    AssetRegistry,
    ConversionResult,
    _apply,
    _cap,
    _same_value,
    _short,
    _unkeep,
    build_positions,
)
from app.convert.to_tpt import extract_tpt
from app.ingest.fundsxml_reader import parse_fundsxml
from app.ingest.openfunds_reader import INSTRUMENT_ID, ISIN, OfDocument
from app.ingest.tpt_reader import TptRow
from app.mapping.openfunds_holdings import add_accrued_interest, holding_to_tpt, with_implied
from app.mapping.openfunds_rules import DEFAULTS, OF_FUND, OF_SHARECLASS, STATIC_RULES
from app.mapping.openfunds_templates import templates
from app.mapping.rules import ASSET_FIELDS, PLACEHOLDER_COUNTRY, PLACEHOLDER_SUPPLIER, PORTFOLIO_FIELDS
from app.mapping.rules import rules_for as tpt_rules_for
from app.model.issues import Issue
from app.model.xmltree import Dropped, Node, serialize_at
from app.schema.model import fundsxml_model, fundsxml_schema_url, fundsxml_version
from app.spec.catalog import load_catalog
from app.validate.xsd import validate_fundsxml

CUSTOM_PREFIX = "OF_"
_TPT = load_catalog("V8")
# Position fields written as amounts in the portfolio currency (``Amount[@ccy={4}]``).
_IN_PORTFOLIO_CCY = frozenset(
    r.field for ctx in ("position", "asset") for r in tpt_rules_for(ctx) if "{4}" in r.path
)
TPT_PREFIX = "TPT_"
FUND_KEYS = (
    "OFST010030",
    "OFST010020",
    "OFST010110",
)  # LEI of fund, legal fund name (incl. umbrella), name only
HOLDING_DATE, HOLDING_CCY = "OFPH000010", "OFPH000020"
SC_CURRENCY, FUND_CURRENCY, PRICE_CURRENCY = "OFST020540", "OFST010410", "OFDY000010"
SC_NAME, FUND_NAME, FUND_NAME_ONLY = "OFST020060", "OFST010020", "OFST010110"
# Dates that tell the reporting date of a record, by preference.
REFERENCE_DATES = ("OFDY100000", "OFDY000036", "OFDY000071", "OFDY000041", "OFDY000021", "OFPH000010")


@dataclass
class OfConvertOptions:
    validate: bool = True
    data_supplier_name: str | None = None
    data_supplier_short: str | None = None
    data_supplier_country: str | None = None
    # TPT values the FundsXML implies (clean = market value, exposure = market value, issuer =
    # instrument name, …) as TPT_<field> custom attributes too. False leaves out those the reverse
    # conversion derives exactly: a smaller document, nothing lost.
    implied_tpt_attributes: bool = True


def rules_for(ctx: str):
    return [r for r in STATIC_RULES if r.ctx == ctx]


def fund_fields() -> frozenset[str]:
    return frozenset(r.field for r in STATIC_RULES if r.ctx == OF_FUND)


def convert_openfunds_to_fundsxml(
    doc: OfDocument, options: OfConvertOptions | None = None
) -> ConversionResult:
    opts = options or OfConvertOptions()
    if opts.implied_tpt_attributes:
        return _convert(doc, opts, None)[0]
    # Leave out the TPT attributes the extraction derives by itself. Whether it does is checked by
    # reading the document back, not predicted: an attribute stays where a value would come back
    # different. Kept attributes only make the derived values more exact, so this settles quickly.
    keep: dict[int, set[str]] = {}
    probe = replace(opts, validate=False)
    for _ in range(3):
        result, written = _convert(doc, probe, keep)
        differs = _not_derived(result.xml, written)
        if not differs:
            return _convert(doc, opts, keep)[0]
        for n, keys in differs.items():
            keep.setdefault(n, set()).update(keys)
    return _convert(doc, opts, None)[0]


def _not_derived(xml: bytes, written: list[tuple[int, dict[str, str], set[str]]]) -> dict[int, set[str]]:
    """Per holding: the TPT values left out that the extraction does not give back unchanged."""
    rows = extract_tpt(parse_fundsxml(xml)).rows
    if len(rows) != len(written):
        return {n: omitted for n, _values, omitted in written if omitted}
    out: dict[int, set[str]] = {}
    for back, (n, values, omitted) in zip(rows, written, strict=True):
        wrong = {k for k in omitted if not _same_value(back.get(k, ""), values.get(k, ""))}
        if wrong:
            out[n] = wrong
    return out


def _convert(
    doc: OfDocument, opts: OfConvertOptions, keep: dict[int, set[str]] | None
) -> tuple[ConversionResult, list[tuple[int, dict[str, str], set[str]]]]:
    """``keep`` None: every TPT value the core structures do not take gets an attribute; else the
    derivable ones (``DERIVED_FIELDS``) only where ``keep`` names them. Also returns, in document
    order, each holding's number, TPT values and the attributes left out."""
    model = fundsxml_model()
    issues: list[Issue] = list(doc.issues)
    # Records are numbered: share classes 1…n, holdings n+1…; origin tags are "<number>:<column>".
    records = [TptRow(r.values, i) for i, r in enumerate(doc.shareclasses, start=1)]
    sources = {i: r.source for i, r in enumerate(doc.shareclasses, start=1)}
    extras = {i: r.extra for i, r in enumerate(doc.shareclasses, start=1)}
    kept: dict[int, set[str]] = {r.source_row: set() for r in records}

    funds = Node("Funds")
    sc_nodes: dict[int, Node] = {}
    fund_nodes: dict[int, Node] = {}
    for group in _group_funds(records):
        fund = funds.add("Fund")
        fund.ensure("Identifiers")
        first = group[0]
        _apply(fund, first, rules_for(OF_FUND), first.values, kept)
        _fund_mandatory(fund, first)
        fund.set("SingleFundFlag", "true")
        _defaults(fund, OF_FUND)
        classes = fund.ensure("SingleFund").ensure("ShareClasses")
        for rec in group:
            sc = classes.add("ShareClass")
            _apply(sc, rec, rules_for(OF_SHARECLASS), rec.values, kept)
            _shareclass_mandatory(sc, rec, fund)
            _defaults(sc, OF_SHARECLASS)
            sc_nodes[rec.source_row] = sc
            fund_nodes[rec.source_row] = fund
        _fund_values_kept(group, kept, issues, sources)

    # -- holdings -----------------------------------------------------------
    assets = AssetRegistry()
    position_nodes: list[tuple[TptRow, Node]] = []
    holding_rows: dict[int, tuple[dict[str, str], dict[str, str], dict[str, set[str]]]] = {}
    core_kept: dict[int, set[str]] = {}
    offset = len(records)
    by_key = _shareclass_index(records)
    groups: OrderedDict[tuple[int, str], list[TptRow]] = OrderedDict()
    unassigned = 0
    for n, h in enumerate(doc.holdings, start=offset + 1):
        tpt, represented = holding_to_tpt(h.values)
        # TPT fields carried as non-openfunds columns (a TPT file sent through openfunds) are the
        # original values and win over the ones derived from openfunds columns.
        tpt = {**tpt, **_tpt_columns(h.extra)}
        add_accrued_interest(tpt)
        holding_rows[n] = (h.values, h.extra, represented)
        sources[n] = h.source
        owner = _owner(h.values, by_key, records)
        if owner is None:
            unassigned += 1
            continue
        when = h.values.get(HOLDING_DATE) or _record_date(records[owner - 1]) or ""
        row = TptRow(tpt, n)
        core_kept[n] = set()
        groups.setdefault((owner, when), []).append(row)
    if unassigned:
        issues.append(
            Issue(
                "error",
                "of_holding_unassigned",
                f"{unassigned} holding(s) name no share class (OFST020000) of the file and the file has "
                "several share classes; they were not converted.",
                params={"n": unassigned},
            )
        )
    for (owner, when), rows in groups.items():
        sc = sc_nodes[owner]
        portfolio = sc.ensure("Portfolios").add("Portfolio")
        portfolio.set("NavDate", when or date.today().isoformat())
        ccy = sc.child("Currency").text if sc.child("Currency") is not None else ""

        def ctx_values(row: TptRow, ccy=ccy) -> dict[str, str]:
            return {"4": ccy, **row.values, "_version": "V7"}

        build_positions(portfolio.ensure("Positions"), rows, assets, ctx_values, core_kept, position_nodes)
        for row in rows:
            # Portfolio-level values a position carries: date and currency of its portfolio.
            if row.get("6") == when:
                core_kept[row.source_row].add("6")
            if row.get("4") and row.get("4") == ccy:
                core_kept[row.source_row].add("4")

    reports, skipped = _template_records(model, records, kept)
    for rec, name, invalid in skipped:
        missing = sorted(
            {m for d in invalid for m in re.findall(r"required element (\w+) missing", d.reason)}
        )
        issues.append(
            Issue(
                "warning",
                "of_template_incomplete",
                f"{sources[rec.source_row]}: the {name} data lacks mandatory fields ({', '.join(missing[:6])}"
                + ("…" if len(missing) > 6 else "")
                + "); its values are kept as custom attributes.",
                params={
                    "template": name,
                    "missing": ", ".join(missing[:6]),
                    "source": sources[rec.source_row],
                },
            )
        )

    # Dry run: learn which values the schema rejects, so they get a custom attribute too.
    dry_f = serialize_at(model, funds, ["Funds"])
    dry_a = serialize_at(model, assets.node, ["AssetMasterData"])
    dry_r = serialize_at(model, reports, ["RegulatoryReportings"])
    _unkeep(kept, dry_f.dropped + dry_f.changed + dry_r.dropped + dry_r.changed)
    _unkeep(core_kept, dry_f.dropped + dry_a.dropped + dry_f.changed + dry_a.changed)

    custom_cols: set[str] = set()
    for rec in records:
        sc = sc_nodes[rec.source_row]
        for col, value in rec.values.items():
            if col not in kept[rec.source_row]:
                _custom(sc, CUSTOM_PREFIX + col, value, f"{rec.source_row}:{col}#custom")
                custom_cols.add(col)
        for header, value in extras[rec.source_row].items():
            _custom(sc, _extra_name(header), value, f"{rec.source_row}:{header}#custom")
    gaps = _shared_asset_gaps(position_nodes) + _portfolio_gaps(groups, position_nodes)
    for row, pos, empty in gaps:
        for key in sorted(empty):
            _custom(pos, _tpt_name(key), "", f"{row.source_row}:{key}#custom")
        if "4" in empty:
            # Without a portfolio currency the amounts in portfolio currency cannot be read back.
            for key in sorted(_IN_PORTFOLIO_CCY & set(row.values)):
                _custom(pos, _tpt_name(key), row.get(key), f"{row.source_row}:{key}#custom")
    omitted: dict[int, tuple[int, dict[str, str], set[str]]] = {}
    for row, pos in position_nodes:
        values, extra, represented = holding_rows[row.source_row]
        reached = with_implied(core_kept[row.source_row])
        implied: set[str] = set()
        if keep is not None:
            missing = {k for keys in represented.values() for k in keys} - reached
            missing |= {_tpt_key(h) for h in extra} - {""}
            implied = (missing & DERIVED_FIELDS) - keep.get(row.source_row, set())
        omitted[id(pos)] = (row.source_row, row.values, implied)
        for col, value in values.items():
            if col in (ISIN, INSTRUMENT_ID) or (col in represented and represented[col] <= reached | implied):
                continue
            custom_cols.add(col)
            if col in represented:
                # A TPT value the core structures did not take: kept in TPT form, which reads back
                # exactly (checked by holding_to_tpt) and is understood by the TPT extraction too.
                for key in sorted(represented[col] - reached - implied):
                    _custom(pos, _tpt_name(key), row.get(key), f"{row.source_row}:{col}#custom")
                continue
            _custom(pos, CUSTOM_PREFIX + col, value, f"{row.source_row}:{col}#custom")
        for header, value in extra.items():
            if _tpt_key(header) not in implied:
                _custom(pos, _extra_name(header), value, f"{row.source_row}:{header}#custom")

    res_f = serialize_at(model, funds, ["Funds"])
    res_a = serialize_at(model, assets.node, ["AssetMasterData"])
    res_r = serialize_at(model, reports, ["RegulatoryReportings"])
    for d in res_r.dropped:
        issues.append(
            _issue(
                d,
                sources,
                "warning",
                "of_template_rejected",
                "Not accepted by the template block (kept as custom attribute)",
            )
        )
    for d in res_f.dropped + res_a.dropped:
        custom = any(o.endswith("#custom") for o in d.origins)
        issues.append(
            _issue(
                d,
                sources,
                "error" if custom else "warning",
                "of_value_lost" if custom else "core_value_rejected",
                "Lost: not accepted as custom attribute either"
                if custom
                else "Not accepted by the core structures (kept as custom attribute)",
            )
        )
    # An empty AssetMasterData (no holdings) is left out of the document, so its gaps are none.
    for d in res_f.invalid + (res_a.invalid if assets.node.children else []) + res_r.invalid:
        issues.append(
            _issue(
                d, sources, "warning", "schema_incomplete", "Mandatory FundsXML content missing or invalid"
            )
        )

    root = etree.Element("FundsXML4", nsmap={"xsi": "http://www.w3.org/2001/XMLSchema-instance"})
    root.set("{http://www.w3.org/2001/XMLSchema-instance}noNamespaceSchemaLocation", fundsxml_schema_url())
    control, ctrl_issues = _control_data(model, records, opts)
    root.append(control)
    issues += ctrl_issues
    if res_f.element is not None:
        root.append(res_f.element)
    if res_a.element is not None and len(res_a.element):
        root.append(res_a.element)
    if res_r.element is not None and len(res_r.element):
        root.append(res_r.element)

    xml = etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True)
    valid, errors = (None, [])
    if opts.validate:
        valid, errors = validate_fundsxml(root)
        if not valid:
            issues.append(
                Issue(
                    "warning",
                    "xsd_invalid",
                    f"The generated document has {len(errors)} XSD validation error(s); "
                    "see the validation list.",
                    params={"n": len(errors)},
                )
            )
    coverage = _coverage(records, kept, list(holding_rows.items()), core_kept, custom_cols)
    stats = {
        "funds": len(funds.children),
        "shareclasses": len(records),
        "portfolios": len(groups),
        "positions": len(position_nodes),
        "assets": len(res_a.element) if res_a.element is not None else 0,
        "fields_in_file": len(doc.columns),
        "custom_attributes": int(root.xpath("count(//CustomAttributes/Attribute)")),
        "coverage": coverage,
    }
    result = ConversionResult(xml, _cap(issues), stats, valid, errors, dict(Counter(i.code for i in issues)))
    return result, [omitted[id(pos)] for pos in _positions_in_order(funds)]


def _positions_in_order(funds: Node) -> list[Node]:
    """The Position nodes in document order: fund, share class, portfolio, position."""
    out: list[Node] = []
    for fund in funds.children:
        classes = fund.find("SingleFund/ShareClasses")
        for sc in classes.children if classes is not None else []:
            portfolios = sc.child("Portfolios")
            for pf in portfolios.children if portfolios is not None else []:
                positions = pf.child("Positions")
                out += positions.children if positions is not None else []
    return out


# ---------------------------------------------------------------------------


def _template_records(model, records: list[TptRow], kept: dict[int, set[str]]):
    """One FinDatEx template record (EMT, EPT, EET, EFT) per share class record with values for it."""
    reports = Node("RegulatoryReportings")
    skipped: list[tuple[TptRow, str, list[Dropped]]] = []
    for tpl in templates():
        record_type = model.type_at(tpl.record.split("/"))
        linkable = record_type is not None and record_type.child("FundOrShareClassIdentifiers") is not None
        for rec in records:
            present = [(f, rec.get(f.of_id)) for f in tpl.fields if rec.get(f.of_id)]
            if not present or all(f.of_id in kept[rec.source_row] for f, _ in present):
                # Nothing, or only values a static rule placed already (OFEP000900, the fund CIC):
                # no template record, and no warning about one that would be incomplete.
                continue
            node = Node(tpl.element)
            if linkable and rec.get(ISIN):
                node.set("FundOrShareClassIdentifiers/ISINs/ISIN", rec.get(ISIN))
            for f, value in present:
                xml = f.to_xml(value)
                if not xml:
                    continue
                origin = f"{rec.source_row}:{f.of_id}"
                if f.many:
                    parent_path, _, leaf = f.path.rpartition("/")
                    parent = node.ensure(parent_path) if parent_path else node
                    for x in xml:
                        item = parent.add(leaf)
                        item.text, item.origin = x, origin
                else:
                    node.set(f.path, xml[0], origin)
            # A record without the template's mandatory content is not written; its values stay
            # custom attributes of the share class.
            res = serialize_at(model, node, tpl.record.split("/"))
            if res.invalid:
                skipped.append((rec, tpl.name, res.invalid))
                continue
            reports.ensure(tpl.container).children.append(node)
            for f, value in present:
                if f.lossless(value):
                    kept[rec.source_row].add(f.of_id)
    return reports, skipped


def _group_funds(records: list[TptRow]) -> list[list[TptRow]]:
    groups: OrderedDict[str, list[TptRow]] = OrderedDict()
    for rec in records:
        key = next((f"{k}={rec.get(k)}" for k in FUND_KEYS if rec.get(k)), f"#{rec.source_row}")
        groups.setdefault(key, []).append(rec)
    return list(groups.values())


def _fund_values_kept(group: list[TptRow], kept: dict[int, set[str]], issues: list[Issue], sources) -> None:
    """Fund-level values are written from the fund's first share class.

    Another share class's value counts as kept only if it equals the written one; otherwise it is
    kept as custom attribute of that share class.
    """
    first = group[0]
    fields = fund_fields()
    written = kept[first.source_row] & fields
    for rec in group[1:]:
        for key in fields:
            value = rec.get(key)
            if not value:
                continue
            if key in written and _same_value(value, first.get(key)):
                kept[rec.source_row].add(key)
            elif not _same_value(value, first.get(key)):
                issues.append(
                    Issue(
                        "info",
                        "of_fund_value_differs",
                        f"{sources[rec.source_row]}: {key} differs from the fund's first share class; "
                        "kept as custom attribute of the share class.",
                        field=key,
                        value=value,
                        params={"field": key, "source": sources[rec.source_row]},
                    )
                )


def _fund_mandatory(fund: Node, first: TptRow) -> None:
    if fund.find("Names/OfficialName") is None:
        name = first.get(FUND_NAME) or first.get(FUND_NAME_ONLY) or first.get(SC_NAME) or first.get(ISIN)
        fund.set("Names/OfficialName", name or "Unknown fund")
    if fund.find("Currency") is None:
        fund.set(
            "Currency",
            first.get(FUND_CURRENCY) or first.get(SC_CURRENCY) or first.get(PRICE_CURRENCY) or "XXX",
        )


def _shareclass_mandatory(sc: Node, rec: TptRow, fund: Node) -> None:
    sc.ensure("Identifiers")
    if sc.find("Names/OfficialName") is None:
        name = rec.get(SC_NAME) or rec.get(FUND_NAME) or rec.get(ISIN) or rec.get(INSTRUMENT_ID)
        sc.set("Names/OfficialName", name or "Unknown share class")
    if sc.find("Currency") is None:
        sc.set("Currency", rec.get(SC_CURRENCY) or rec.get(PRICE_CURRENCY) or fund.child("Currency").text)


def _defaults(node: Node, ctx: str) -> None:
    for c, parent, child, value in DEFAULTS:
        if c != ctx:
            continue
        holder = node.find(parent) if parent else node
        if holder is not None and holder.find(child) is None:
            holder.set(child, value)


def _shareclass_index(records: list[TptRow]) -> dict[str, int]:
    out: dict[str, int] = {}
    for rec in records:
        for key in (ISIN, INSTRUMENT_ID):
            if rec.get(key):
                out.setdefault(rec.get(key).upper(), rec.source_row)
    return out


def _owner(values: dict[str, str], by_key: dict[str, int], records: list[TptRow]) -> int | None:
    for key in (ISIN, INSTRUMENT_ID):
        if values.get(key) and values[key].upper() in by_key:
            return by_key[values[key].upper()]
    return records[0].source_row if len(records) == 1 else None


def _record_date(rec: TptRow) -> str:
    return next((rec.get(k) for k in REFERENCE_DATES if rec.get(k)), "")


def _shared_asset_gaps(position_nodes: list[tuple[TptRow, Node]]) -> list[tuple[TptRow, Node, set[str]]]:
    """Asset master data is written once per instrument, from its first holding.

    A later holding of the same instrument that leaves one of those fields empty gets an empty
    ``TPT_<field>`` marker, or the reverse conversion would copy the first holding's value.
    """
    first: dict[str, TptRow] = {}
    out = []
    for row, pos in position_nodes:
        owner = first.setdefault(pos.child("UniqueID").text, row)
        if owner is not row:
            empty = {k for k in ASSET_FIELDS if owner.get(k) and not row.get(k)}
            if empty:
                out.append((row, pos, empty))
    return out


def _portfolio_gaps(groups, position_nodes) -> list[tuple[TptRow, Node, set[str]]]:
    """Portfolio-level TPT values a holding leaves empty while others of its portfolio give them.

    The reverse conversion would take the portfolio's (share class) value for them; an empty
    ``TPT_<field>`` marker keeps the holding as it was.
    """
    pos_of = {row.source_row: pos for row, pos in position_nodes}
    out = []
    for rows in groups.values():
        filled = {k for r in rows for k in r.values if k in PORTFOLIO_FIELDS}
        for r in rows:
            empty = filled - set(r.values)
            if empty and r.source_row in pos_of:
                out.append((r, pos_of[r.source_row], empty))
    return out


def _tpt_name(key: str) -> str:
    return TPT_PREFIX + (_TPT.by_key[key].num_data if key in _TPT.by_key else key)


def _tpt_columns(extra: dict[str, str]) -> dict[str, str]:
    """TPT values of ``TPT_<field>`` columns by field key."""
    return {key: value for header, value in extra.items() if (key := _tpt_key(header))}


def _tpt_key(header: str) -> str:
    """The TPT field of a ``TPT_<field>_<name>`` column ("" for any other column)."""
    if not header.startswith(TPT_PREFIX):
        return ""
    return header[len(TPT_PREFIX) :].split("_", 1)[0].lower()


def _extra_name(header: str) -> str:
    return header if header.startswith(TPT_PREFIX) else CUSTOM_PREFIX + header


def _custom(node: Node, name: str, value: str, origin: str) -> None:
    attr = node.ensure(f"CustomAttributes/Attribute[Name={name}]")
    attr.set("Type", "T")
    attr.set("ValueText", value, origin, keep_empty=True)


def _control_data(model, records: list[TptRow], opts: OfConvertOptions):
    first = records[0] if records else TptRow({}, 0)
    node = Node("ControlData")
    node.set("UniqueDocumentID", f"OF-{uuid.uuid4().hex[:20]}")
    node.set("DocumentGenerated", datetime.now(UTC).replace(microsecond=0, tzinfo=None).isoformat())
    node.set("Version", fundsxml_version())
    dates = [d for d in (_record_date(r) for r in records) if d]
    node.set("ContentDate", max(dates)[:10] if dates else date.today().isoformat())
    supplier = (
        opts.data_supplier_name or first.get("OFST001020") or first.get("OFST001000") or PLACEHOLDER_SUPPLIER
    )
    country = opts.data_supplier_country or first.get("OFST001035") or PLACEHOLDER_COUNTRY
    node.set("DataSupplier/SystemCountry", country.upper()[:2])
    node.set("DataSupplier/Short", opts.data_supplier_short or _short(supplier))
    node.set("DataSupplier/Name", supplier)
    node.set("DataSupplier/Type", "IC")
    node.set("DataOperation", "INITIAL")
    res = serialize_at(model, node, ["ControlData"])
    issues = [
        Issue(
            "warning",
            "control_data",
            f"ControlData value rejected: {d.reason}",
            path=d.path,
            value=d.value or None,
        )
        for d in res.dropped + res.invalid
    ]
    return res.element, issues


def _issue(d: Dropped, sources: dict[int, str], level: str, code: str, prefix: str) -> Issue:
    tags = [o.split("#")[0].split(":", 1) for o in d.origins if ":" in o]
    cols = sorted({c for _, c in tags})
    where = sources.get(int(tags[0][0]), "") if tags else ""
    return Issue(
        level,
        code,
        f"{prefix}: {d.reason}" + (f" ({where})" if where else ""),
        field=",".join(cols) or None,
        path=d.path,
        value=d.value or None,
        detail=d.reason,
    )


def _coverage(records, kept, holdings, core_kept, custom_cols: set[str]) -> dict[str, dict[str, bool]]:
    """Per openfunds column of the file: did it reach the core structures, a custom attribute?"""
    out: dict[str, dict[str, bool]] = {}
    for rec in records:
        for col in rec.values:
            c = out.setdefault(col, {"core": False, "custom": False})
            c["core"] |= col in kept[rec.source_row]
    for n, (values, _extra, represented) in holdings:
        reached = with_implied(core_kept.get(n, set()))
        for col in values:
            c = out.setdefault(col, {"core": False, "custom": False})
            c["core"] |= col in represented and represented[col] <= reached
    for col, c in out.items():
        c["custom"] = col in custom_cols
    return out
