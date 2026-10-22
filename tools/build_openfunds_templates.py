"""Generate backend/app/mapping/openfunds_templates.json: openfunds template fields → FundsXML paths.

The openfunds fields of the FinDatEx templates (OFEM = EMT, OFEP = EPT, OFEE = EET, OFEF = EFT)
name their template field ("EMT: 00001_EMT_Version"). FundsXML's template blocks document the same
numbers on their elements ("00001 EMT Version V4S3", "EPT 01010-…"), on a group for its children
("02010-02020-02030" for OneYear/HalfRHP/RHP) or as a range for a group of value/coverage children
("30020 - 30050"). This script indexes those numbers per template and joins them with the catalog.

Usage: python tools/build_openfunds_templates.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from lxml import etree

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.schema.model import FUNDSXML_XSD
from app.spec.openfunds import load_openfunds

TARGET = ROOT / "backend" / "app" / "mapping" / "openfunds_templates.json"
XS = "{http://www.w3.org/2001/XMLSchema}"
LANG = "{http://www.w3.org/XML/1998/namespace}lang"

# Template -> (record element path from the document root, prefix of its openfunds fields).
TEMPLATES = {
    "EMT": (
        "RegulatoryReportings/DirectReporting/EMT_V4_3/FinancialInstrument",
        "OFEM",
    ),
    "EET": ("RegulatoryReportings/DirectReporting/EET1.1.3/EET1.1.3", "OFEE"),
    "EFT": ("RegulatoryReportings/DirectReporting/EFTs/EFT", "OFEF"),
    "EPT": ("RegulatoryReportings/IndirectReporting/PRIIPS_V20/EPTV2", "OFEP"),
}
_PAI = "PrincipalAdverseIndicators"
_VSC = ("Value", "ConsideredInInvestmentStrategy", "Coverage", "EligibleAssets")


def _quad(nums: tuple[str, str, str, str], group: str) -> dict[tuple[str, str], str]:
    return {
        ("EET", n): f"{_PAI}/{group}/{leaf}" for n, leaf in zip(nums, _VSC, strict=True)
    }


def _autocall(scenario: str, applied: str, when: str) -> dict[tuple[str, str], str]:
    base = f"PerformanceScenario/Return{scenario}"
    return {
        ("EPT", applied): f"{base}/AutoCallApplied",
        ("EPT", when): f"{base}/AutocallDate",
    }


# Template fields the schema documents without (or with a wrong) number: (template, number) -> path.
MANUAL: dict[tuple[str, str], str] = {
    ("EET", "00010"): "DataSetInformation/DataSetInformation/Version",
    (
        "EET",
        "13000",
    ): "DataSetInformation/ManufacturerWebsiteInformationStewardshipAndEngagement",
    **_quad(
        ("31020", "31030", "31040", "31045"),
        "SocialAndEmployeeMatters/CompaniesWithoutMonitoringCompliance_UN_GCP_Or_OECD_ME_Guidelines",
    ),
    **_quad(
        ("31490", "31500", "31505", "31510"),
        "MoreClimateAndEnvironmentRelatedIndicators/EnergyEfficiency/CompaniesWithoutCarbonEmissionReductionInitiatives",
    ),
    **_quad(
        ("31671", "31672", "31673", "31674"),
        "MoreClimateAndEnvironmentRelatedIndicators/WaterWasteAndLandProtection/WaterUsageAndRecyclingPercentage",
    ),
    **_quad(
        ("32040", "32050", "32060", "32070"),
        "MoreClimateAndEnvironmentRelatedIndicators/GreenSecurities/BondsNotissuedUnderUnionLegislationOnEnvironmentallySustainableBonds",
    ),
    **_quad(
        ("33120", "33130", "33140", "33145"),
        "MoreSocialAndEmployeeMatters/CorruptionAndBribery/CompaniesInsufficientReactionsOnCorruptionAndBribery",
    ),
    ("EPT", "00001"): "DataSetInformation/Version",
    ("EPT", "00006"): "DataSetInformation/Data_ReportingNarratives",
    ("EPT", "00007"): "DataSetInformation/DataReportingCosts",
    (
        "EPT",
        "00008",
    ): "DataSetInformation/DataReportingAdditionalRequirementsGermanMOPs",
    ("EPT", "00009"): "DataSetInformation/AdditionalInformationStructuredProductsRIY",
    ("EPT", "00080"): "GeneralPortfolioInformation/PortfolioPRIIPSCategory",
    ("EPT", "01095"): "RiskAssessment/IsSRIAdjusted",
    ("EPT", "06070"): "CountrySpecificData/DE/CapitalPreservation/UsesPI",
    **_autocall("Unfavorable", "02032", "02035"),
    **_autocall("Moderate", "02062", "02065"),
    **_autocall("Favorable", "02092", "02095"),
    **_autocall("Stress", "02122", "02125"),
    (
        "EMT",
        "08120",
    ): "CostsAndChargesExPost/StructuredSecurity/NotionalReferenceAmount",
    ("EFT", "01030"): "DataSetInformation/SubmitterEntityInformation/IdentifierType",
    (
        "EFT",
        "01040",
    ): "DataSetInformation/SubmitterEntityInformation/PositionInTheDistributionChain",
}
# By OF-ID where two openfunds fields share a number (EET 30000 is the reference period and the frequency).
MANUAL_IDS: dict[str, str | None] = {
    "OFEE300000": None,  # PAI beginning of reference period: no element in EET 1.1.3
    "OFEE300001": "PrincipalAdverseIndicators/PAISnapshotFrequency",
    "OFEP000700": None,  # EPT 2.1 KID publication date; 00070 in the EPT 2.0 block is the reference date
}
# Numbers the schema documents on the wrong element (EFT submitter fields carry the recipient numbers).
WRONG_NUMBERS = {("EFT", "02030"), ("EFT", "02040")}
# openfunds value -> schema value where the code lists differ only in spelling.
CODES: dict[str, dict[str, str]] = {
    "OFEM000010": {"v4.3": "V4S3"},
    "OFEF000100": {"v1": "V1"},
}
_LEAD = re.compile(r"^\s*(?:C?EPT\s+|EMT\s+|EET\s+|EFT\s+)?(\d{5,6})(?![\d])")
_NUMS = re.compile(r"(?<![\d.])(\d{5,6})(?![\d.%])")
_RANGE = re.compile(r"(?<![\d-])(\d{5,6})\s*-\s*(\d{5,6})(?![\d]|\s*-\s*\d)")
_CHAIN = re.compile(r"\d{5,6}(?:-\d{5,6}){2,}")


class Xsd:
    def __init__(self, path: Path):
        root = etree.parse(str(path)).getroot()
        self.ctypes = {c.get("name"): c for c in root.iterfind(f"{XS}complexType")}
        self.stypes = {c.get("name"): c for c in root.iterfind(f"{XS}simpleType")}
        self.groups = {g.get("name"): g for g in root.iterfind(f"{XS}group")}
        self.root = next(
            e for e in root.iterfind(f"{XS}element") if e.get("name") == "FundsXML4"
        )

    def ctype(self, el):
        t = el.get("type")
        return self.ctypes.get(t) if t in self.ctypes else el.find(f"{XS}complexType")

    def children(self, node):
        for ch in node:
            if ch.tag == f"{XS}element":
                yield ch
            elif ch.tag in (f"{XS}sequence", f"{XS}choice", f"{XS}all"):
                yield from self.children(ch)
            elif ch.tag == f"{XS}group" and ch.get("ref"):
                yield from self.children(self.groups[ch.get("ref")])
            elif ch.tag in (f"{XS}complexContent", f"{XS}simpleContent"):
                for ext in ch:
                    if ext.get("base") in self.ctypes:
                        yield from self.children(self.ctypes[ext.get("base")])
                    yield from self.children(ext)

    def find(self, path: str):
        el = self.root
        for name in path.split("/"):
            el = next(c for c in self.children(self.ctype(el)) if c.get("name") == name)
        return el

    def simple(self, el) -> tuple[str, list[str]]:
        """(type name or base, enumerations) of a simple element."""
        t = el.get("type") or ""
        st = self.stypes.get(t) if t in self.stypes else el.find(f"{XS}simpleType")
        if st is None:
            return t, []
        enums = [e.get("value") for e in st.iter(f"{XS}enumeration")]
        return t or (
            st.find(f"{XS}restriction").get("base")
            if st.find(f"{XS}restriction") is not None
            else ""
        ), enums


def doc(el) -> str:
    d = el.find(f"{XS}annotation/{XS}documentation[@{LANG}='en']")
    return " ".join((d.text or "").split()) if d is not None else ""


def index(xsd: Xsd, record_path: str) -> dict[str, list[dict]]:
    """FinDatEx number -> [{path, type, enums, many}, …] for one template record.

    A number can be documented twice (the fund and the structured security variant of an EMT cost).
    """
    out: dict[str, list[dict]] = {}

    def put(num, info):
        out.setdefault(num, []).append(info)

    def leaf_info(el, path):
        t, enums = xsd.simple(el)
        return {
            "path": path,
            "type": t,
            "enums": enums,
            "many": el.get("maxOccurs") == "unbounded",
        }

    def walk(el, path, depth):
        ct = xsd.ctype(el)
        text = doc(el)
        if ct is None:
            m = _LEAD.match(text)
            if m:
                put(m.group(1), leaf_info(el, path))
            return
        if depth > 14:
            return
        kids = list(xsd.children(ct))
        # Leaf children that carry no number of their own get the group's numbers.
        bare = [k for k in kids if xsd.ctype(k) is None and not _LEAD.match(doc(k))]
        chain = _CHAIN.search(text)
        rng = None if chain else _RANGE.search(text)
        nums = chain.group(0).split("-") if chain else _NUMS.findall(text)
        if bare and rng and len(bare) > 1:
            a, b = int(rng.group(1)), int(rng.group(2))
            if (b - a) % (len(bare) - 1) == 0:
                step = (b - a) // (len(bare) - 1)
                width = len(rng.group(1))
                nums = [str(a + i * step).zfill(width) for i in range(len(bare))]
            else:
                nums = []
        if (
            bare
            and nums
            and (len(nums) == len(bare) or (chain and len(nums) < len(bare)))
        ):
            for num, k in zip(nums, bare, strict=False):
                put(
                    num,
                    leaf_info(k, f"{path}/{k.get('name')}" if path else k.get("name")),
                )
        for k in kids:
            walk(k, f"{path}/{k.get('name')}" if path else k.get("name"), depth + 1)

    walk(xsd.find(record_path), "", 0)
    return out


def leaves(xsd: Xsd, record_path: str) -> dict[str, dict]:
    """Every simple element below the record: path -> info."""
    out: dict[str, dict] = {}

    def walk(el, path, depth):
        ct = xsd.ctype(el)
        if ct is None:
            t, enums = xsd.simple(el)
            out[path] = {
                "path": path,
                "type": t,
                "enums": enums,
                "many": el.get("maxOccurs") == "unbounded",
            }
            return
        if depth > 14:
            return
        for k in xsd.children(ct):
            walk(k, f"{path}/{k.get('name')}" if path else k.get("name"), depth + 1)

    walk(xsd.find(record_path), "", 0)
    return out


_STOP = {
    "the",
    "of",
    "in",
    "a",
    "an",
    "to",
    "and",
    "for",
    "by",
    "or",
    "with",
    "on",
    "is",
    "are",
    "financial",
    "instrument",
}
_SPELLING = {"favourable": "favorable", "unfavourable": "unfavorable"}


def _tokens(text: str) -> list[str]:
    words = re.findall(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+", text.replace("_", " "))
    out = []
    for w in words:
        w = _SPELLING.get(w.lower(), w.lower())
        if w not in _STOP:
            out.append(w)
    return out


def best_hit(name: str, hits: list[dict]) -> dict | None:
    """Of several elements with one number, the one whose path shares most words with the field name."""
    if len(hits) <= 1:
        return hits[0] if hits else None
    words = set(_tokens(name))
    return max(
        hits, key=lambda h: len(words & set(_tokens(h["path"].replace("/", " "))))
    )


_METRIC_PARTS = {*_VSC, "Weight", "Number"}


def match_sibling(
    name: str, prev: tuple[str, str] | None, candidates: dict[str, dict], used: set[str]
):
    """The next sibling of the previous field's element, when both fields name the same metric.

    PAI metrics are groups of value / considered in strategy / coverage / eligible assets whose
    openfunds names are often cut short; the first one matches by name, the others follow it.
    """
    if prev is None:
        return None
    words, prev_words = (
        _tokens(name.split("_", 1)[-1]),
        _tokens(prev[0].split("_", 1)[-1]),
    )
    if len(words) < 3 or words[:3] != prev_words[:3]:
        return None
    parent = re.sub(r"\[[^]]*\]", "", prev[1]).rsplit("/", 1)[0]
    siblings = [p for p in candidates if p.rsplit("/", 1)[0] == parent]
    pred_parent = prev[1].rsplit("/", 1)[0]
    leaf = re.sub(r"\[[^]]*\]", "", prev[1]).rsplit("/", 1)[1]
    if leaf not in [p.rsplit("/", 1)[1] for p in siblings]:
        return None
    names = [p.rsplit("/", 1)[1] for p in siblings]
    if not {leaf, *names} <= _METRIC_PARTS:
        return None
    for nxt in names[names.index(leaf) + 1 :]:
        path = f"{pred_parent}/{nxt}"
        if path not in used:
            return {**candidates[f"{parent}/{nxt}"], "path": path}
    return None


_NACE_LEAF = {
    "valu": "Value",
    "cons": "ConsideredInInvestmentStrategy",
    "cov": "Coverage",
    "elig": "EligibleAssets",
}


def match_nace(name: str, candidates: dict[str, dict]) -> dict | None:
    """``…_Per_High_Impact_Climate_Sector_NACE_A_Value`` → ``…/NACE_Values[NACE_Category=A]/Values/Value``."""
    m = re.search(r"_NACE_([A-Z])_([A-Za-z]+)$", name)
    if not m:
        return None
    leaf = next(
        (v for k, v in _NACE_LEAF.items() if m.group(2).lower().startswith(k)), None
    )
    hits = [p for p in candidates if p.endswith(f"NACE_Values/Values/{leaf}")]
    if leaf is None or len(hits) != 1:
        return None
    path = hits[0].replace("NACE_Values/", f"NACE_Values[NACE_Category={m.group(1)}]/")
    return {**candidates[hits[0]], "path": path}


def match_by_name(
    name: str, candidates: dict[str, dict], used: set[str]
) -> dict | None:
    """The leaf whose last two or three path steps spell the end of the openfunds field name."""
    words = _tokens(name.split("_", 1)[1] if "_" in name else name)
    nace = re.search(r"_NACE_([A-Z])_", name)
    target = "".join(words)
    best, best_len, tie = None, 0, False
    for path, info in candidates.items():
        if path in used:
            continue
        steps = path.split("/")
        for k in (3, 2):
            key = "".join(t for step in steps[-k:] for t in _tokens(step))
            if len(key) < 8 or not target.endswith(key):
                continue
            if nace and "NACE_Values" not in path:
                continue
            if len(key) > best_len:
                best, best_len, tie = info, len(key), False
            elif len(key) == best_len and best is not info:
                tie = True
            break
    if best is None or tie:
        return None
    if nace:
        best = {
            **best,
            "path": best["path"].replace(
                "NACE_Values/", f"NACE_Values[NACE_Category={nace.group(1)}]/"
            ),
        }
    return best


def main() -> None:
    xsd = Xsd(FUNDSXML_XSD)
    catalog = load_openfunds()
    entries, missing = [], {}
    for template, (record, prefix) in TEMPLATES.items():
        idx = index(xsd, record)
        all_leaves = leaves(xsd, record)
        # Paths named by hand are reserved for their field.
        used: set[str] = {p for (t, _), p in MANUAL.items() if t == template}
        used |= {p for p in MANUAL_IDS.values() if p}
        prev: tuple[str, str] | None = None
        for f in catalog.fields:
            ref = f.ref(template)
            if f.prefix != prefix or ref is None or not f.active:
                continue
            hits = (
                idx.get(ref.num)
                or idx.get(ref.num.zfill(5))
                or idx.get(ref.num.lstrip("0").zfill(5))
                or []
            )
            if (template, ref.num) in WRONG_NUMBERS:
                hits = []
            hit = None
            if f.of_id in MANUAL_IDS and MANUAL_IDS[f.of_id] is None:
                missing.setdefault(template, []).append(f"{f.of_id} {ref.name}")
                continue
            if f.of_id in MANUAL_IDS or (template, ref.num) in MANUAL:
                path = MANUAL_IDS.get(f.of_id) or MANUAL[(template, ref.num)]
                hit = all_leaves.get(re.sub(r"\[[^]]*\]", "", path))
                if hit is None:
                    raise SystemExit(
                        f"MANUAL path not in the schema: {template} {ref.num} {path}"
                    )
                hit = {**hit, "path": path}
            hit = hit or best_hit(f.name, [h for h in hits if h["path"] not in used])
            if hit is None:
                hit = match_nace(ref.name, all_leaves) or match_by_name(
                    ref.name, all_leaves, used
                )
            if hit is None:
                hit = match_by_name(f"{ref.num}_{f.name}", all_leaves, used)
            if hit is None:
                hit = match_sibling(ref.name, prev, all_leaves, used)
            if hit is not None:
                used.add(hit["path"])
                prev = (ref.name, hit["path"])
            else:
                prev = None
            if hit is None:
                missing.setdefault(template, []).append(f"{f.of_id} {ref.name}")
                continue
            percent = hit["type"] == "PercentageType" and "decimal" in f.values.lower()
            entries.append(
                {
                    "id": f.of_id,
                    "template": template,
                    "num": ref.num,
                    "path": hit["path"],
                    "type": hit["type"],
                    "enums": hit["enums"],
                    "many": hit["many"],
                    "percent": percent,
                    "codes": CODES.get(f.of_id, {}),
                }
            )
    payload = {
        "records": {t: r for t, (r, _) in TEMPLATES.items()},
        "fields": entries,
        "unmatched": missing,
    }
    TARGET.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", "utf-8")
    for template, (_, prefix) in TEMPLATES.items():
        n = sum(1 for e in entries if e["template"] == template)
        print(
            f"{template}: {n} fields mapped, {len(missing.get(template, []))} unmatched"
        )


if __name__ == "__main__":
    main()
