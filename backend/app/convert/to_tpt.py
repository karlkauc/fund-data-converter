"""FundsXML 4 → TPT rows.

Sources, in order of precedence for every field:

1. ``CustomAttributes`` named ``TPT_<field>`` on a core position – the exact
   original value kept by this converter (or by anyone following the same
   convention);
2. the TPT block ``TripartiteTemplateSolvencyII_V7``;
3. the core structures (fund, NAV, position, referenced asset).

Without a TPT block, every share class becomes a TPT portfolio (field 1 = its
ISIN). Its positions come from ``ShareClass/Portfolios``, else from the fund
portfolio ``FundDynamicData/Portfolios``, which is then repeated for each share
class; the fund portfolio is never a TPT portfolio of its own. Only a fund
without share classes is reported on fund level. Values FundsXML only implies
are completed by ``app.convert.derive``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from functools import lru_cache

from lxml import etree

from app.convert.derive import amount, complete_portfolio, complete_position, dec
from app.mapping.rules import PLACEHOLDER_COUNTRY, PLACEHOLDER_SUPPLIER, Rule, rules_for
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
class CorePortfolio:
    """A TPT portfolio in the core structures: a share class (or a fund without any) and its holdings."""

    fund: etree._Element
    share_class: etree._Element | None
    nav: etree._Element | None
    price: etree._Element | None
    portfolio: etree._Element
    control: etree._Element | None = None

    @property
    def holder(self) -> etree._Element:
        return self.share_class if self.share_class is not None else self.fund


@dataclass
class TptExtract:
    version: str
    rows: list[dict[str, str]]
    source: str  # "block", "core", "block+core"
    issues: list[Issue] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    # Core ``Position`` element of each row (None for a TPT block position without one).
    positions: list[etree._Element | None] = field(default_factory=list)


def extract_tpt(root: etree._Element, version: str | None = None) -> TptExtract:
    issues: list[Issue] = []
    block = root.find(BLOCK_PATH)
    core_portfolios = _core_portfolios(root, issues)
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
    positions: list[etree._Element | None] = []
    if block is not None:
        source = "block"
        used_core: set[int] = set()
        for pf in block.iterfind("Portfolio"):
            pf_values: dict[str, str] = {}
            _read(pf, rules_for("tpt_portfolio"), pf_values)
            core = _match_core(pf_values, core_portfolios, used_core)
            core_positions = core.portfolio.findall("Positions/Position") if core is not None else []
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
                positions.append(core_positions[idx] if core_positions else None)
    else:
        source = "core"
        for core in core_portfolios:
            base: dict[str, str] = {}
            _read_portfolio(core, base)
            if not base.get("6") and core.portfolio.findtext("NavDate"):
                base["6"] = core.portfolio.findtext("NavDate")
            fx = _PortfolioCurrency(core, base)
            rates = _PortfolioRates(core.portfolio)
            pf_rows = []
            for pos in core.portfolio.iterfind("Positions/Position"):
                values = dict(base)
                _merge_core(values, core, pos, assets)
                fx.fill(values, pos)
                _qc_value(values, pos, _pc_per_qc(values, pos, rates))
                complete_position(values, fx.exposure(pos), _pc_per_qc(values, pos, rates))
                pf_rows.append(values)
                positions.append(pos)
            complete_portfolio(pf_rows)
            rows += pf_rows
            fx.report(base, issues)

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
    return TptExtract(out_version, rows, source, issues, stats, positions)


# ---------------------------------------------------------------------------


@lru_cache(maxsize=4096)
def _compiled(path: str) -> etree.XPath:
    return etree.XPath(_xpath(path))


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
        found = _compiled(path)(el)
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


def _read_portfolio(core: CorePortfolio, values: dict[str, str]) -> None:
    if core.share_class is None:
        _read(core.fund, rules_for("fund"), values)
        if core.nav is not None:
            _read(core.nav, rules_for("nav"), values)
    else:
        _read(core.share_class, rules_for("shareclass"), values)
        if core.nav is not None:
            _read(core.nav, rules_for("sc_nav"), values)
        if core.price is not None:
            _read(core.price, rules_for("sc_price"), values)
    _read(core.fund, rules_for("fund_info"), values)
    if core.control is not None:
        reported: dict[str, str] = {}
        _read(core.control, rules_for("control"), reported)
        # The document date may precede a share class valued later; the reporting date may not.
        if reported.get("7") and values.get("6", "") > reported["7"]:
            reported["7"] = values["6"]
        # Our own TPT → FundsXML output names no real fund issuer.
        if reported.get("117") == PLACEHOLDER_SUPPLIER:
            del reported["117"]
        if reported.get("122", "").upper() == PLACEHOLDER_COUNTRY:
            del reported["122"]
        for key, value in reported.items():
            if not values.get(key):
                values[key] = value


def _merge_core(values: dict[str, str], core: CorePortfolio, position: etree._Element, assets: dict) -> None:
    """Custom attributes override; core rules only fill fields that are still empty."""
    custom = _custom_values(position)
    values.update(custom)
    _read_portfolio(core, values)
    # The holding's currency wins over the instrument's: positions may share one master data entry.
    _read(position, [r for r in rules_for("position") if r.field == "21"], values)
    asset = assets.get(position.findtext("UniqueID"))
    if asset is not None:
        _read(asset, rules_for("asset"), values)
    _read(position, rules_for("position"), values)


def _core_portfolios(root: etree._Element, issues: list[Issue]) -> list[CorePortfolio]:
    out = []
    control = root.find("ControlData")
    for fund in root.iterfind("Funds/Fund"):
        fund_portfolios = fund.findall("FundDynamicData/Portfolios/Portfolio")
        classes = fund.findall("SingleFund/ShareClasses/ShareClass")
        if not classes:
            navs = fund.findall("FundDynamicData/TotalAssetValues/TotalAssetValue")
            for portfolio in fund_portfolios:
                out.append(CorePortfolio(fund, None, _on_date(navs, portfolio), None, portfolio, control))
            continue
        for sc in classes:
            own = sc.findall("Portfolios/Portfolio")
            portfolios = own or fund_portfolios
            if not portfolios:
                isin = _first_id(sc)
                issues.append(
                    Issue(
                        "info",
                        "shareclass_no_portfolio",
                        f"Share class {isin} has no portfolio (neither its own nor the fund's); skipped.",
                        params={"shareclass": isin},
                    )
                )
                continue
            navs = sc.findall("TotalAssetValues/TotalAssetValue")
            prices = sc.findall("Prices/Price")
            for portfolio in portfolios:
                nav = _on_date(navs, portfolio)
                if not own and _no_assets(nav):
                    isin, date = _first_id(sc), portfolio.findtext("NavDate") or ""
                    issues.append(
                        Issue(
                            "info",
                            "shareclass_inactive",
                            f"Share class {isin} has no net assets on {date}; skipped.",
                            params={"shareclass": isin, "date": date},
                        )
                    )
                    continue
                out.append(CorePortfolio(fund, sc, nav, _on_date(prices, portfolio), portfolio, control))
    return out


def _no_assets(nav: etree._Element | None) -> bool:
    """A share class NAV of zero: not (or no longer) invested, so it has no share of the fund portfolio."""
    if nav is None:
        return False
    amounts = [dec(a.text) for a in nav.iterfind("TotalNetAssetValue/Amount")]
    return bool(amounts) and all(a == 0 for a in amounts)


def _on_date(candidates: list[etree._Element], portfolio: etree._Element) -> etree._Element | None:
    """The NAV/price of the portfolio's date (official first), else the first one."""
    date = portfolio.findtext("NavDate")
    same = [c for c in candidates if c.findtext("NavDate") == date]
    official = [
        c
        for c in same
        if (c.findtext("TotalAssetNature") or c.findtext("PriceNature") or "OFFICIAL") == "OFFICIAL"
    ]
    return next(iter(official or same or candidates), None)


def _first_id(el: etree._Element) -> str:
    return next(((e.text or "").strip() for e in el.iterfind("Identifiers/*") if (e.text or "").strip()), "?")


# Exposure types that give the commitment value of a derivative, by preference.
COMMITMENT_TYPES = ("commitment approach", "commitment", "derivate meldeverordnung cesr", "exposure")
# Position amounts in portfolio currency that a fund portfolio may only carry in the fund currency.
PC_AMOUNTS = ("24", "25", "126")


class _PortfolioCurrency:
    """Amounts in portfolio currency for a fund portfolio reported for a share class in another currency.

    Positions of a fund portfolio usually carry amounts in the fund currency only. The rate comes
    from the share class NAV in both currencies, else from the portfolio's positions (FX rates, or
    an amount given in both currencies).
    """

    def __init__(self, core: CorePortfolio, base: dict[str, str]):
        self.ccy = base.get("4", "")
        self.fund_ccy = (core.fund.findtext("Currency") or "").strip()
        self.rate: Decimal | None = None
        self.derived = self.missing = 0
        if core.share_class is None or not self.ccy or not self.fund_ccy or self.ccy == self.fund_ccy:
            self.fund_ccy = ""
            return
        if core.nav is not None:
            pc = _amount(core.nav, "TotalNetAssetValue", self.ccy)
            fc = _amount(core.nav, "TotalNetAssetValue", self.fund_ccy)
            if pc and fc:
                self.rate = pc / fc
        if self.rate is None:
            self.rate = _portfolio_rate(core.portfolio, self.fund_ccy, self.ccy)

    def fill(self, values: dict[str, str], position: etree._Element) -> None:
        if not self.fund_ccy or values.get("24"):
            return
        in_fund_ccy = {k: v for k, v in values.items() if k not in PC_AMOUNTS}
        in_fund_ccy["4"] = self.fund_ccy
        _read(position, rules_for("position"), in_fund_ccy)
        if not in_fund_ccy.get("24"):
            return
        if self.rate is None:
            self.missing += 1
            return
        for key in PC_AMOUNTS:
            if not values.get(key) and (d := dec(in_fund_ccy.get(key))) is not None:
                values[key] = amount(d * self.rate)
        self.derived += 1

    def exposure(self, position: etree._Element) -> Decimal | None:
        """Commitment value of the position in portfolio currency."""
        by_type = {
            (e.findtext("Type") or "").strip().lower(): e for e in position.iterfind("Exposures/Exposure")
        }
        exposure = next((by_type[t] for t in COMMITMENT_TYPES if t in by_type), None)
        if exposure is None:
            return None
        value = _amount(exposure, "Value", self.ccy)
        if value is None and self.fund_ccy and self.rate is not None:
            fc = _amount(exposure, "Value", self.fund_ccy)
            value = fc * self.rate if fc is not None else None
        return value

    def report(self, base: dict[str, str], issues: list[Issue]) -> None:
        params = {"portfolio": base.get("1", "?"), "ccy": self.ccy, "fund_ccy": self.fund_ccy}
        if self.derived:
            issues.append(
                Issue(
                    "info",
                    "fx_derived",
                    f"Portfolio {params['portfolio']}: market values in {self.ccy} (24) of {self.derived} "
                    f"position(s) converted from {self.fund_ccy} at the rate of the share class NAV.",
                    field="24",
                    params={**params, "n": self.derived},
                )
            )
        if self.missing:
            issues.append(
                Issue(
                    "warning",
                    "fx_missing",
                    f"Portfolio {params['portfolio']}: {self.missing} position(s) have no market value in "
                    f"{self.ccy} (24), and the share class NAV gives no rate from {self.fund_ccy}.",
                    field="24",
                    params={**params, "n": self.missing},
                )
            )


def _portfolio_rate(portfolio: etree._Element, src: str, dst: str) -> Decimal | None:
    """Rate src → dst as the portfolio's positions state it on the valuation date."""
    for pos in portfolio.iterfind("Positions/Position"):
        if (rate := _position_rate(pos, src, dst)) is not None:
            return rate
    return None


def _position_rate(position: etree._Element, src: str, dst: str) -> Decimal | None:
    for fx in position.iterfind("FXRates/FXRate"):
        rate = dec(fx.text)
        if not rate:
            continue
        mul = fx.get("mulDiv", "M").upper() != "D"
        if (fx.get("fromCcy"), fx.get("toCcy")) == (src, dst):
            return rate if mul else 1 / rate
        if (fx.get("fromCcy"), fx.get("toCcy")) == (dst, src):
            return 1 / rate if mul else rate
    for holder in position.xpath(".//*[Amount]"):
        amounts = {a.get("ccy"): dec(a.text) for a in holder.iterfind("Amount")}
        if amounts.get(src) and amounts.get(dst):
            return amounts[dst] / amounts[src]
    return None


class _PortfolioRates:
    """Exchange rates the positions of a portfolio state, looked up once per currency pair."""

    def __init__(self, portfolio: etree._Element):
        self.portfolio = portfolio
        self.cache: dict[tuple[str, str], Decimal | None] = {}

    def get(self, src: str, dst: str) -> Decimal | None:
        if (src, dst) not in self.cache:
            self.cache[(src, dst)] = _portfolio_rate(self.portfolio, src, dst)
        return self.cache[(src, dst)]


def _pc_per_qc(
    values: dict[str, str], position: etree._Element, rates: _PortfolioRates | None = None
) -> Decimal | None:
    """Rate quotation → portfolio currency.

    From the two market values, else from the position's FX rates, else from any amount the
    position gives in both currencies (e.g. an exposure), else from the other positions.
    """
    qc, pc = dec(values.get("22")), dec(values.get("24"))
    if qc and pc:
        return pc / qc
    src, dst = values.get("21", ""), values.get("4", "")
    if src and src == dst:
        return Decimal(1)
    if not src or not dst:
        return None
    rate = _position_rate(position, src, dst)
    if rate is None and rates is not None:
        rate = rates.get(src, dst)
    return rate


# Position elements priced per unit: market value in quotation currency = units × price.
UNIT_PRICED = ("Equity", "REIT", "Right", "Warrant", "Certificate", "ShareClass")


def _qc_value(values: dict[str, str], position: etree._Element, pc_per_qc: Decimal | None) -> None:
    """Market value in quotation currency (22) when the position only gives it in other currencies."""
    if values.get("22"):
        return
    if pc_per_qc and (pc := dec(values.get("24"))) is not None:
        values["22"] = amount(pc / pc_per_qc)
        return
    for kind in UNIT_PRICED:
        el = position.find(kind)
        if el is None:
            continue
        units = dec(el.findtext("Units") or el.findtext("Shares"))
        price = _amount(el, "Price", values.get("21", ""))
        if units is not None and price is not None:
            values["22"] = amount(units * price)
        return


def _amount(el: etree._Element, path: str, ccy: str) -> Decimal | None:
    for a in el.iterfind(f"{path}/Amount"):
        if a.get("ccy") == ccy and (d := dec((a.text or "").strip())) is not None:
            return d
    return None


def _match_core(pf_values: dict[str, str], core: list[CorePortfolio], used: set[int]):
    """The core portfolio for a block portfolio: same identifier and date, else the next unused."""
    code, date = pf_values.get("1", ""), pf_values.get("6", "")
    for idx, c in enumerate(core):
        if idx in used or (c.portfolio.findtext("NavDate") or "") != date:
            continue
        ids = {(e.text or "").strip() for e in c.holder.iterfind("Identifiers//*")}
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
