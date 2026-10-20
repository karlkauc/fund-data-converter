"""FundsXML 4 → TPT rows.

Sources, in order of precedence for every field:

1. ``CustomAttributes`` named ``TPT_<field>`` on a core position – the exact
   original value kept by this converter (or by anyone following the same
   convention);
2. the TPT block ``TripartiteTemplateSolvencyII_V7``;
3. the core structures (fund, NAV, position, referenced asset).

Without a TPT block, every ``Fund/…/Portfolio`` becomes a TPT portfolio and
its positions are read from the core structures alone.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from lxml import etree

from app.mapping.rules import Rule, rules_for
from app.model.issues import Issue
from app.spec.catalog import VERSIONS, load_catalog

CUSTOM_PREFIX = "TPT_"
BLOCK_PATH = "RegulatoryReportings/IndirectReporting/TripartiteTemplateSolvencyII_V7"
OLDER_BLOCKS = (
    "TripartiteTemplateSolvencyII_V6",
    "TripartiteTemplateSolvencyII_V5",
    "TripartiteTemplateSolvencyII",
)


@dataclass
class TptExtract:
    version: str
    rows: list[dict[str, str]]
    source: str  # "block", "core", "block+core"
    issues: list[Issue] = field(default_factory=list)
    stats: dict = field(default_factory=dict)


def extract_tpt(root: etree._Element, version: str | None = None) -> TptExtract:
    issues: list[Issue] = []
    block = root.find(BLOCK_PATH)
    core_portfolios = _core_portfolios(root)
    assets = {a.findtext("UniqueID"): a for a in root.iterfind("AssetMasterData/Asset")}
    for older in OLDER_BLOCKS:
        if root.find(f"RegulatoryReportings/IndirectReporting/{older}") is not None:
            issues.append(
                Issue(
                    "warning",
                    "older_tpt_block",
                    f"{older} is not supported; only the V7 block and the core structures are read.",
                    params={"block": older},
                )
            )

    rows: list[dict[str, str]] = []
    if block is not None:
        source = "block"
        used_core: set[int] = set()
        for pf in block.iterfind("Portfolio"):
            pf_values: dict[str, str] = {}
            _read(pf, rules_for("tpt_portfolio"), pf_values)
            core = _match_core(pf_values, core_portfolios, used_core)
            core_positions = core[2].findall("Positions/Position") if core is not None else []
            block_positions = pf.findall("Positions/Position")
            if core is not None and len(core_positions) != len(block_positions):
                issues.append(
                    Issue(
                        "warning",
                        "core_mismatch",
                        f"Portfolio {pf_values.get('1', '?')}: the core portfolio has "
                        f"{len(core_positions)} positions, the TPT block {len(block_positions)}; "
                        "core data is not merged.",
                        params={
                            "portfolio": pf_values.get("1", "?"),
                            "core": len(core_positions),
                            "block": len(block_positions),
                        },
                    )
                )
                core_positions = []
            for idx, pos in enumerate(block_positions):
                values = dict(pf_values)
                _read(pos, rules_for("tpt_position"), values)
                if core_positions:
                    # The block holds every field; the core position only adds the values the
                    # block could not take (custom attributes), never approximations.
                    custom = _custom_values(core_positions[idx])
                    if custom:
                        source = "block+core"
                        values.update(custom)
                rows.append(values)
    else:
        source = "core"
        for fund, nav, portfolio in core_portfolios:
            base: dict[str, str] = {}
            _read(fund, rules_for("fund"), base)
            if nav is not None:
                _read(nav, rules_for("nav"), base)
            if not base.get("6") and portfolio.findtext("NavDate"):
                base["6"] = portfolio.findtext("NavDate")
            for pos in portfolio.iterfind("Positions/Position"):
                values = dict(base)
                _merge_core(values, (fund, nav, portfolio), pos, assets)
                rows.append(values)

    detected = _detect_version(rows)
    out_version = (version or detected).upper()
    if out_version not in VERSIONS:
        raise ValueError(f"unsupported TPT version {version}")
    for r in rows:
        r.pop("_version", None)
        r["1000"] = (
            r.get("1000") if detected == out_version and r.get("1000") else _version_label(out_version)
        )
        for k in [k for k, v in r.items() if not v]:
            del r[k]
    if not rows:
        issues.append(
            Issue(
                "error",
                "no_positions",
                "The document contains no positions (neither a TPT "
                "block nor Funds/Fund/…/Portfolio/Positions).",
            )
        )
    _missing_mandatory(rows, out_version, issues)
    stats = {
        "portfolios": len({(r.get("1"), r.get("6")) for r in rows}),
        "positions": len(rows),
        "source": source,
    }
    return TptExtract(out_version, rows, source, issues, stats)


# ---------------------------------------------------------------------------


def _xpath(path: str) -> str:
    """Rule path syntax → XPath (predicates ``[Child=value]`` / ``[@a=value]``)."""
    out = []
    for seg in _segments(path):
        if "[" in seg:
            name, pred = seg[:-1].split("[", 1)
            key, value = pred.split("=", 1)
            out.append(f"{name}[{key}={_literal(value)}]")
        else:
            out.append(seg)
    return "/".join(out)


def _segments(path: str) -> list[str]:
    segs, depth, cur = [], 0, ""
    for ch in path:
        depth += ch == "["
        depth -= ch == "]"
        if ch == "/" and depth == 0:
            segs.append(cur)
            cur = ""
        else:
            cur += ch
    segs.append(cur)
    return [s for s in segs if s]


def _literal(value: str) -> str:
    if "'" not in value:
        return f"'{value}'"
    if '"' not in value:
        return f'"{value}"'
    parts = value.split("'")
    return "concat(" + ', "\'", '.join(f"'{p}'" for p in parts) + ")"


def _read(el: etree._Element, rules: list[Rule], values: dict[str, str]) -> None:
    for rule in rules:
        if rule.field in values or not rule.applies_reverse(values):
            continue
        path = rule.resolve(values)
        if path is None:
            continue
        found = el.xpath(_xpath(path))
        if not found:
            continue
        node = found[0]
        text = node if isinstance(node, str) else (node.text or "")
        text = str(text).strip()
        if not text:
            continue
        value = rule.transform.from_xml(text, values)
        if value:
            values[rule.field] = value
            for key, v in rule.reverse_sets:
                values.setdefault(key, v)


def _custom_values(el: etree._Element) -> dict[str, str]:
    out = {}
    for attr in el.iterfind("CustomAttributes/Attribute"):
        name = attr.findtext("Name") or ""
        if not name.startswith(CUSTOM_PREFIX):
            continue
        key = name[len(CUSTOM_PREFIX) :].split("_", 1)[0].lower()
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


def _merge_core(values: dict[str, str], core, position: etree._Element, assets: dict) -> None:
    """Custom attributes override; core rules only fill fields that are still empty."""
    fund, nav, _portfolio = core
    custom = _custom_values(position)
    values.update(custom)
    _read(fund, rules_for("fund"), values)
    if nav is not None:
        _read(nav, rules_for("nav"), values)
    asset = assets.get(position.findtext("UniqueID"))
    if asset is not None:
        _read(asset, rules_for("asset"), values)
    _read(position, rules_for("position"), values)


def _core_portfolios(root: etree._Element) -> list[tuple]:
    out = []
    for fund in root.iterfind("Funds/Fund"):
        navs = fund.findall("FundDynamicData/TotalAssetValues/TotalAssetValue")
        for portfolio in fund.iterfind("FundDynamicData/Portfolios/Portfolio"):
            date = portfolio.findtext("NavDate")
            nav = next((n for n in navs if n.findtext("NavDate") == date), navs[0] if navs else None)
            out.append((fund, nav, portfolio))
    return out


def _match_core(pf_values: dict[str, str], core: list[tuple], used: set[int]):
    """The core portfolio for a block portfolio: same fund identifier and date, else the next unused."""
    code, date = pf_values.get("1", ""), pf_values.get("6", "")
    for idx, (fund, _nav, portfolio) in enumerate(core):
        if idx in used or (portfolio.findtext("NavDate") or "") != date:
            continue
        ids = {(e.text or "").strip() for e in fund.iterfind("Identifiers//*")}
        if code in ids:
            used.add(idx)
            return core[idx]
    for idx in range(len(core)):
        if idx not in used:
            used.add(idx)
            return core[idx]
    return None


def _detect_version(rows: list[dict[str, str]]) -> str:
    for r in rows:
        label = r.get("1000", "").upper()
        if "V8" in label.replace(" ", "") or label.startswith("8."):
            return "V8"
    if any(r.get("150") or r.get("151") for r in rows):
        return "V8"
    return "V7"


def _version_label(version: str) -> str:
    from app.spec.catalog import VERSION_LABELS

    return VERSION_LABELS[version]


def _missing_mandatory(rows: list[dict[str, str]], version: str, issues: list[Issue]) -> None:
    catalog = load_catalog(version)
    always = [
        f
        for f in catalog.fields
        if f.mandatory
        and f.num_key in ("1", "2", "3", "4", "5", "6", "7", "12", "14", "15", "17", "21", "22", "24", "26")
    ]
    missing: dict[str, int] = {}
    for r in rows:
        for f in always:
            if not r.get(f.num_key):
                missing[f.num_key] = missing.get(f.num_key, 0) + 1
    for key, n in missing.items():
        issues.append(
            Issue(
                "warning",
                "mandatory_missing",
                f"Mandatory field {catalog.by_key[key].num_data} is empty in {n} row(s).",
                field=key,
                params={"name": catalog.by_key[key].num_data, "n": n},
            )
        )
