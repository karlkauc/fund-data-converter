"""TPT → FundsXML 4.

Rows are grouped into portfolios by portfolio id (field 1) and valuation
date (field 6). Each portfolio becomes

* one ``Portfolio`` in the TPT block (lossless 1:1 store, optional), and
* one ``Funds/Fund`` with a single share class (core, optional): the share
  class carries the portfolio id (field 1), price, NAV and a ``Portfolio`` of
  ``Position`` elements that reference ``AssetMasterData/Asset`` entries. The
  fund itself only gets the mandatory name and currency.

Values that end up nowhere – fields without a block element (17b, 114,
V8 fields 150/151), values the schema rejects, values a transform cannot
represent exactly – are kept as ``CustomAttributes`` named ``TPT_<field>``
on the core position (or fund, for portfolio-level fields), so the reverse
conversion restores the original file.

FundsXML 4.2.11 has no V8 block, so V8 data goes into the V7 block as well.
The V7 block requires a few elements V8 no longer maintains (fund issuer code
types and sector, option direction, index name); ``_block_row`` fills them
from the V8 data so the block stays complete (see ``V7_BLOCK_FILLERS``).
"""

from __future__ import annotations

import re
import uuid
from collections import Counter, OrderedDict
from dataclasses import dataclass, field
from datetime import UTC, datetime

from lxml import etree

from app.ingest.tpt_reader import TptDocument, TptRow
from app.mapping.rules import (
    ASSET_FIELDS,
    BLOCK_RULES,
    PLACEHOLDER_COUNTRY,
    PLACEHOLDER_SUPPLIER,
    PORTFOLIO_FIELDS,
    Rule,
    rules_for,
)
from app.mapping.transforms import asset_type, position_element
from app.model.issues import Issue
from app.model.xmltree import Dropped, Node, parse_decimal, serialize_at
from app.schema.model import fundsxml_model, fundsxml_schema_url, fundsxml_version
from app.spec.catalog import load_catalog
from app.validate.xsd import validate_fundsxml

TPT_BLOCK = ["RegulatoryReportings", "IndirectReporting", "TripartiteTemplateSolvencyII_V7"]
CUSTOM_PREFIX = "TPT_"
MAX_ISSUES_PER_CODE = 25


@dataclass
class ConvertOptions:
    include_block: bool = True
    include_core: bool = True
    validate: bool = True
    data_supplier_name: str | None = None
    data_supplier_short: str | None = None
    data_supplier_country: str | None = None


@dataclass
class PortfolioGroup:
    key: tuple[str, str]
    rows: list[TptRow]


@dataclass
class ConversionResult:
    xml: bytes
    issues: list[Issue]
    stats: dict
    valid: bool | None
    validation_errors: list[str] = field(default_factory=list)
    issue_totals: dict[str, int] = field(default_factory=dict)  # per code, before capping


def group_portfolios(rows: list[TptRow]) -> list[PortfolioGroup]:
    groups: OrderedDict[tuple[str, str], list[TptRow]] = OrderedDict()
    for row in rows:
        groups.setdefault((row.get("1"), row.get("6")), []).append(row)
    return [PortfolioGroup(k, v) for k, v in groups.items()]


class _Origins:
    """Origin tags ``"<row>:<field>"`` so dropped values can be traced to a row."""

    @staticmethod
    def tag(row: TptRow, key: str) -> str:
        return f"{row.source_row}:{key}"

    @staticmethod
    def parse(tag: str) -> tuple[int, str]:
        r, k = tag.split(":", 1)
        return int(r), k


def convert_tpt_to_fundsxml(doc: TptDocument, options: ConvertOptions | None = None) -> ConversionResult:
    opts = options or ConvertOptions()
    if not (opts.include_block or opts.include_core):
        raise ValueError("select at least one of the TPT block or the core FundsXML structures")
    model = fundsxml_model()
    catalog = load_catalog(doc.version)
    issues: list[Issue] = list(doc.issues)
    groups = group_portfolios(doc.rows)

    # Which fields of which row reached the document losslessly: {source_row: {numKey}}
    kept: dict[int, set[str]] = {r.source_row: set() for r in doc.rows}
    all_dropped: list[Dropped] = []
    invalid: list[Dropped] = []

    def ctx_values(row: TptRow) -> dict[str, str]:
        return {**row.values, "_version": doc.version}

    # -- TPT block --------------------------------------------------------
    block_el = None
    if opts.include_block:
        block = Node("TripartiteTemplateSolvencyII_V7")
        pf_rules = [r for r in BLOCK_RULES if r.ctx == "tpt_portfolio"]
        pos_rules = [r for r in BLOCK_RULES if r.ctx == "tpt_position"]
        for group in groups:
            pf = block.add("Portfolio")
            first = _block_row(group.rows[0], doc.version)
            _apply(pf, first, pf_rules, ctx_values(first), kept)
            positions = pf.ensure("Positions")
            for row in group.rows:
                pos = positions.add("Position")
                row = _block_row(row, doc.version)
                _apply(pos, row, pos_rules, ctx_values(row), kept)
                if not row.get("17"):
                    pos.ensure("InstrumentName")  # mandatory; empty, as the source has it
        res = serialize_at(model, block, TPT_BLOCK)
        del block  # the loose tree is no longer needed; large files need the memory
        block_el = res.element
        _unkeep(kept, res.dropped + res.changed)
        _portfolio_fields_kept(groups, kept, issues)
        all_dropped += res.dropped
        invalid += res.invalid

    # -- core ---------------------------------------------------------------
    funds_el = assets_el = None
    custom_keys: set[str] = set()
    core_kept: dict[int, set[str]] = {r.source_row: set() for r in doc.rows}
    if opts.include_core:
        funds, assets, position_nodes = _build_core(groups, ctx_values, core_kept)
        if not opts.include_block:
            # Dry run: learn which values the core structures reject, so they get a fallback too.
            dry_f = serialize_at(model, funds, ["Funds"])
            dry_a = serialize_at(model, assets, ["AssetMasterData"])
            _unkeep(core_kept, dry_f.dropped + dry_a.dropped + dry_f.changed + dry_a.changed)
            _portfolio_fields_kept(groups, core_kept, [])
        reached_by_row = kept if opts.include_block else core_kept
        shared = _shared_values(groups, position_nodes, opts.include_block)
        for row, pos in position_nodes:
            reached = reached_by_row[row.source_row]
            for key, value in row.values.items():
                if key not in reached:
                    _custom_attribute(pos, catalog, key, value, _Origins.tag(row, key) + "#custom")
                    custom_keys.add(key)
            # A value shared by the portfolio (or asset) that this row leaves empty.
            for key in shared.get(row.source_row, ()):
                _custom_attribute(pos, catalog, key, "", _Origins.tag(row, key) + "#custom")
        res_f = serialize_at(model, funds, ["Funds"])
        res_a = serialize_at(model, assets, ["AssetMasterData"])
        funds_el, assets_el = res_f.element, res_a.element
        del funds, assets, position_nodes
        for d in res_f.dropped + res_a.dropped:
            if any(o.endswith("#custom") for o in d.origins):
                all_dropped.append(d)  # a fallback attribute itself was rejected: a real loss
            elif opts.include_block:
                issues.append(
                    _issue_from_dropped(
                        d,
                        "info",
                        "core_value_skipped",
                        "Not written to the core structures (kept in the TPT block)",
                    )
                )
            else:
                issues.append(
                    _issue_from_dropped(
                        d,
                        "warning",
                        "core_value_rejected",
                        "Not accepted by the core structures (kept as custom attribute)",
                    )
                )
        invalid += res_f.invalid + res_a.invalid

    # -- assemble -----------------------------------------------------------
    root = etree.Element("FundsXML4", nsmap={"xsi": "http://www.w3.org/2001/XMLSchema-instance"})
    root.set("{http://www.w3.org/2001/XMLSchema-instance}noNamespaceSchemaLocation", fundsxml_schema_url())
    control, ctrl_issues = _control_data(model, doc, groups, opts)
    root.append(control)
    issues += ctrl_issues
    if funds_el is not None:
        root.append(funds_el)
    if assets_el is not None:
        root.append(assets_el)
    if block_el is not None:
        rr = etree.SubElement(root, "RegulatoryReportings")
        etree.SubElement(rr, "IndirectReporting").append(block_el)

    issues += _summarise_block_drops(all_dropped, opts) if opts.include_block else []
    for d in invalid:
        issues.append(
            _issue_from_dropped(
                d, "warning", "schema_incomplete", "Mandatory FundsXML content missing or invalid"
            )
        )
    issues += _v8_notes(doc)

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
    stats = {
        "portfolios": len(groups),
        "positions": len(doc.rows),
        "assets": len(assets_el) if assets_el is not None else 0,
        "fields_in_file": len(doc.columns),
        "custom_attributes": int(root.xpath("count(//CustomAttributes/Attribute)")),
        "coverage": _coverage(
            doc, kept if opts.include_block else None, core_kept if opts.include_core else None, custom_keys
        ),
    }
    return ConversionResult(xml, _cap(issues), stats, valid, errors, dict(Counter(i.code for i in issues)))


# ---------------------------------------------------------------------------


def _coverage(doc: TptDocument, block_kept, core_kept, custom_keys: set[str]) -> dict[str, dict[str, bool]]:
    """Per field present in the file: where its values ended up."""
    present: dict[str, list[int]] = {}
    for row in doc.rows:
        for key in row.values:
            present.setdefault(key, []).append(row.source_row)
    out = {}
    for key, rows in present.items():
        out[key] = {
            "block": block_kept is not None and all(key in block_kept[r] for r in rows),
            "core": core_kept is not None and any(key in core_kept[r] for r in rows),
            "custom": key in custom_keys,
        }
    return out


def _apply(
    node: Node, row: TptRow, rules: list[Rule], ctx: dict[str, str], kept: dict[int, set[str]]
) -> None:
    conflicts: set[str] = set()
    for rule in rules:
        value = row.get(rule.field)
        if not value or rule.read_only or not rule.applies(ctx):
            continue
        path = rule.resolve(ctx)
        if path is None:
            continue
        xml_value, lossless = rule.transform.to_xml(value, ctx)
        if xml_value is None:
            continue
        if xml_value == "":
            node.ensure(path)
        else:
            held = node.find(path)
            if held is not None and held.text is not None and not _same_value(held.text, xml_value):
                # Another field already holds a different value here (e.g. 22 and 24 in one
                # currency); keep that one, this value stays a custom attribute.
                conflicts.add(rule.field)
                continue
            node.set(path, xml_value, _Origins.tag(row, rule.field))
        if lossless:
            kept[row.source_row].add(rule.field)
    kept[row.source_row] -= conflicts


def _same_value(a: str, b: str) -> bool:
    if a == b:
        return True
    try:
        return parse_decimal(a) == parse_decimal(b)
    except ValueError:
        return False


def _unkeep(kept: dict[int, set[str]], dropped: list[Dropped]) -> None:
    for d in dropped:
        for tag in d.origins:
            row, key = _Origins.parse(tag)
            kept.get(row, set()).discard(key)


def _portfolio_fields_kept(
    groups: list[PortfolioGroup], kept: dict[int, set[str]], issues: list[Issue]
) -> None:
    """Portfolio-level values are written once, from the first row of a portfolio.

    Another row's value counts as kept only if it equals that written value;
    otherwise it is stored with the row as a custom attribute.
    """
    for group in groups:
        first = group.rows[0]
        written = kept[first.source_row] & PORTFOLIO_FIELDS
        for row in group.rows[1:]:
            for key in PORTFOLIO_FIELDS:
                value = row.get(key)
                if not value:
                    continue
                if value == first.get(key) and key in written:
                    kept[row.source_row].add(key)
                elif value != first.get(key):
                    issues.append(
                        Issue(
                            "info",
                            "portfolio_value_differs",
                            f"Field {key} differs from the first row of portfolio {group.key[0]}; "
                            "kept as custom attribute of the position.",
                            field=key,
                            row=row.source_row,
                            value=value,
                            params={"portfolio": group.key[0]},
                        )
                    )


def _shared_values(groups: list[PortfolioGroup], position_nodes, block: bool) -> dict[int, set[str]]:
    """Fields a row leaves empty although the value written for its portfolio/asset is not.

    The reverse conversion would otherwise copy the shared value into that row.
    """
    out: dict[int, set[str]] = {}
    for group in groups:
        first = group.rows[0]
        for row in group.rows[1:]:
            empty = {k for k in PORTFOLIO_FIELDS if first.get(k) and not row.get(k)}
            if empty:
                out.setdefault(row.source_row, set()).update(empty)
        for row in group.rows:
            # A bond's quantity stands in for the missing nominal (Bond/Nominal) and reads back as 19.
            if row.get("18") and not row.get("19") and asset_type(row.get("12")) == "BO":
                out.setdefault(row.source_row, set()).add("19")
    if not block:
        # Core only: asset master data is written once per instrument.
        asset_first: dict[str, TptRow] = {}
        for row, pos in position_nodes:
            aid = pos.child("UniqueID").text
            owner = asset_first.setdefault(aid, row)
            if owner is not row:
                empty = {k for k in ASSET_FIELDS if owner.get(k) and not row.get(k)}
                if empty:
                    out.setdefault(row.source_row, set()).update(empty)
    return out


@dataclass
class AssetRegistry:
    """``AssetMasterData`` built alongside the positions: one ``Asset`` per instrument."""

    node: Node = field(default_factory=lambda: Node("AssetMasterData"))
    ids: dict[tuple[str, str, str, str], str] = field(default_factory=dict)
    used: set[str] = field(default_factory=set)
    written: set[str] = field(default_factory=set)


def build_positions(
    positions: Node,
    rows: list[TptRow],
    assets: AssetRegistry,
    ctx_values,
    core_kept: dict[int, set[str]],
    position_nodes: list[tuple[TptRow, Node]],
) -> None:
    """``Position`` elements for TPT rows, each referencing its ``AssetMasterData/Asset``."""
    for row in rows:
        aid = _asset_id(row, assets.ids, assets.used)
        pos = positions.add("Position")
        pos.set("UniqueID", aid)
        _apply(pos, row, rules_for("position"), ctx_values(row), core_kept)
        element = position_element(row)
        if element:
            pos.ensure(element)
        position_nodes.append((row, pos))
        if aid not in assets.written:
            assets.written.add(aid)
            asset = assets.node.add("Asset")
            asset.set("UniqueID", aid)
            _apply(asset, row, rules_for("asset"), ctx_values(row), core_kept)
            if not row.get("17"):
                asset.ensure("Name")  # mandatory; empty, as the source has it


def _build_core(groups: list[PortfolioGroup], ctx_values, core_kept: dict[int, set[str]]):
    funds = Node("Funds")
    assets = AssetRegistry()
    position_nodes: list[tuple[TptRow, Node]] = []
    for group in groups:
        first = group.rows[0]
        ctx = ctx_values(first)
        fund = funds.add("Fund")
        # The portfolio id is the share class's; the fund (whose id TPT does not carry) keeps
        # its mandatory elements only.
        fund.ensure("Identifiers")
        _apply(fund, first, [r for r in rules_for("fund") if r.field not in ("1", "2")], ctx, core_kept)
        _apply(fund, first, rules_for("fund_info"), ctx, core_kept)
        fund.set("SingleFundFlag", "true")
        share_class = fund.ensure("SingleFund").ensure("ShareClasses").add("ShareClass")
        _apply(share_class, first, rules_for("shareclass"), ctx, core_kept)
        share_class.ensure("Identifiers")
        if first.get("8"):
            price = share_class.ensure("Prices").add("Price")
            price.set("ActionCode", "C")
            price.set("PriceNature", "OFFICIAL")
            _apply(price, first, rules_for("sc_price"), ctx, core_kept)
        nav = share_class.ensure("TotalAssetValues").add("TotalAssetValue")
        _apply(nav, first, rules_for("sc_nav"), ctx, core_kept)
        nav.set("TotalAssetNature", "OFFICIAL")
        portfolio = share_class.ensure("Portfolios").add("Portfolio")
        portfolio.set("NavDate", first.get("6"), _Origins.tag(first, "6"))
        build_positions(
            portfolio.ensure("Positions"), group.rows, assets, ctx_values, core_kept, position_nodes
        )
    return funds, assets.node, position_nodes


# Elements the V7 block requires that V8 no longer maintains, and where V8 data implies them:
# 115/119/140 must be LEIs in V8 (code type 1), the index is identified by its reference (34), a
# callable bond is exercised by the issuer and a putable one by the bearer, and a fund issuer is a
# collective investment undertaking (NACE K64.30).
V7_BLOCK_FILLERS = "116/120/141 = 1, 118 = K6430, 36 = field 34, 44 = I (Cal) / B (Put)"
_FUND_NACE = "K6430"
_OPTION_DIRECTION = {"cal": "I", "put": "B"}


def _block_row(row: TptRow, version: str) -> TptRow:
    """The row as written to the V7 block: for V8 data, with the V7-only required elements filled."""
    if version != "V8":
        return row
    v = row.values
    extra: dict[str, str] = {}
    for code, code_type in (("115", "116"), ("119", "120"), ("140", "141")):
        if v.get(code) and not v.get(code_type):
            extra[code_type] = "1"
    if v.get("115") and not v.get("118"):
        extra["118"] = _FUND_NACE
    if v.get("34") and not v.get("36"):
        extra["36"] = v["34"]
    if not v.get("44") and (direction := _OPTION_DIRECTION.get(v.get("42", "").strip().lower())):
        extra["44"] = direction
    return TptRow({**v, **extra}, row.source_row) if extra else row


def _custom_attribute(node: Node, catalog, key: str, value: str, origin: str) -> None:
    spec = catalog.by_key.get(key)
    name = CUSTOM_PREFIX + (spec.num_data if spec else key)
    attr = node.ensure(f"CustomAttributes/Attribute[Name={name}]")
    attr.set("Type", "T")
    attr.set("ValueText", value, origin, keep_empty=True)


_ID_SAFE = re.compile(r"[^A-Za-z0-9_.\-]")


def _asset_id(row: TptRow, ids: dict[tuple[str, str, str, str], str], used: set[str]) -> str:
    # The quotation currency is part of the key: one ISIN listed in two currencies is two assets.
    key = (row.get("15"), row.get("14"), "" if row.get("14") else row.get("17"), row.get("21"))
    if key in ids:
        return ids[key]
    base = "A_" + _ID_SAFE.sub("_", row.get("14") or row.get("17") or f"row{row.source_row}")[:60]
    candidate, n = base, 1
    while candidate in used:
        n += 1
        candidate = f"{base}_{n}"
    ids[key] = candidate
    used.add(candidate)
    return candidate


def _control_data(model, doc: TptDocument, groups: list[PortfolioGroup], opts: ConvertOptions):
    first = groups[0].rows[0]
    node = Node("ControlData")
    node.set("UniqueDocumentID", f"TPT-{uuid.uuid4().hex[:20]}")
    node.set("DocumentGenerated", datetime.now(UTC).replace(microsecond=0, tzinfo=None).isoformat())
    node.set("Version", fundsxml_version())
    node.set("ContentDate", first.get("7") or first.get("6"))
    supplier_name = opts.data_supplier_name or first.get("117") or PLACEHOLDER_SUPPLIER
    country = opts.data_supplier_country or first.get("122") or PLACEHOLDER_COUNTRY
    node.set("DataSupplier/SystemCountry", country.upper())
    node.set("DataSupplier/Short", opts.data_supplier_short or _short(supplier_name))
    node.set("DataSupplier/Name", supplier_name)
    node.set("DataSupplier/Type", "IC")
    node.set("DataOperation", "INITIAL")
    res = serialize_at(model, node, ["ControlData"])
    issues = [
        _issue_from_dropped(d, "warning", "control_data", "ControlData value rejected")
        for d in res.dropped + res.invalid
    ]
    return res.element, issues


def _short(name: str) -> str:
    letters = re.sub(r"[^A-Za-z0-9]", "", name.upper())
    return letters[:16] or "TPTCONV"


def _issue_from_dropped(d: Dropped, level: str, code: str, prefix: str) -> Issue:
    rows = sorted({_Origins.parse(o)[0] for o in d.origins if ":" in o})
    keys = sorted({_Origins.parse(o)[1].split("#")[0] for o in d.origins if ":" in o})
    return Issue(
        level,
        code,
        f"{prefix}: {d.reason}",
        field=",".join(keys) or None,
        row=rows[0] if rows else None,
        path=d.path,
        value=d.value or None,
        detail=d.reason,
    )


def _summarise_block_drops(dropped: list[Dropped], opts: ConvertOptions) -> list[Issue]:
    out = []
    for d in dropped:
        target = "kept as custom attribute" if opts.include_core else "lost"
        out.append(
            _issue_from_dropped(
                d,
                "warning" if opts.include_core else "error",
                "block_value_rejected",
                f"Not accepted by the TPT block ({target})",
            )
        )
    return out


def _v8_notes(doc: TptDocument) -> list[Issue]:
    if doc.version != "V8":
        return []
    return [
        Issue(
            "info",
            "v8_in_v7_block",
            "FundsXML 4.2.11 has no TPT V8 block: V8 data is written to the V7 block; "
            "fields 150/151, the full version label (1000), codes e1/e2/e3 (56) and issuer "
            "code type 2 (48/51/82/85) are kept as custom attributes. Elements the V7 block "
            f"requires are filled from the V8 data: {V7_BLOCK_FILLERS}.",
            params={"fillers": V7_BLOCK_FILLERS},
        )
    ]


def _cap(issues: list[Issue]) -> list[Issue]:
    counts: dict[str, int] = {}
    out = []
    for i in issues:
        counts[i.code] = counts.get(i.code, 0) + 1
        if counts[i.code] <= MAX_ISSUES_PER_CODE:
            out.append(i)
    for n in counts.values():
        if n > MAX_ISSUES_PER_CODE:
            out.append(
                Issue(
                    "info",
                    "more_messages",
                    f"… {n - MAX_ISSUES_PER_CODE} more message(s) of this kind",
                    params={"n": n - MAX_ISSUES_PER_CODE},
                )
            )
    return out
