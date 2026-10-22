"""GET /api/mapping/{version} – the field mapping table (static, cacheable).

``version`` is V7 or V8 for the TPT fields, ``openfunds`` for the openfunds fields.
"""

from __future__ import annotations

from functools import lru_cache

from fastapi import APIRouter, HTTPException, Response

from app.mapping.openfunds_holdings import INSTRUMENT_IDS, ISSUER_LEI, OTHER_ID, UNDERLYING_IDS, field_pairs
from app.mapping.openfunds_rules import OF_FUND, STATIC_RULES
from app.mapping.openfunds_templates import templates
from app.mapping.rules import BLOCK_RULES, CORE_RULES
from app.spec.catalog import VERSIONS, load_catalog
from app.spec.openfunds import load_openfunds
from app.usage.context import emit

router = APIRouter()

_CTX_PREFIX = {
    "tpt_portfolio": "…/TripartiteTemplateSolvencyII_V7/Portfolio/",
    "tpt_position": "…/TripartiteTemplateSolvencyII_V7/Portfolio/Positions/Position/",
    "shareclass": "Fund/SingleFund/ShareClasses/ShareClass/",
    "sc_nav": "…/ShareClass/TotalAssetValues/TotalAssetValue/",
    "sc_price": "…/ShareClass/Prices/Price/",
    "fund": "Funds/Fund/",
    "fund_info": "Funds/Fund/",
    "control": "ControlData/",
    "nav": "Fund/FundDynamicData/TotalAssetValues/TotalAssetValue/",
    "position": "Fund/…/Portfolio/Positions/Position/",
    "asset": "AssetMasterData/Asset/",
}


_OF_PREFIX = {True: "Funds/Fund/", False: "Fund/SingleFund/ShareClasses/ShareClass/"}


@lru_cache(maxsize=2)
def mapping_table(version: str) -> dict:
    catalog = load_catalog(version)
    fields = []
    for f in catalog.fields:
        block = [_describe(r) for r in BLOCK_RULES if r.field == f.num_key]
        core = [_describe(r) for r in CORE_RULES if r.field == f.num_key]
        status = "block+core" if block and core else "block" if block else "core" if core else "custom"
        fields.append(
            {
                "key": f.num_key,
                "name": f.num_data,
                "definition": f.definition[:400],
                "flag": f.sii_flag,
                "block": block,
                "core": core,
                "status": status,
            }
        )
    return {"version": version, "fields": fields}


@lru_cache(maxsize=1)
def openfunds_mapping_table() -> dict:
    """Per openfunds field: the FundsXML core path, template path or TPT field it goes to.

    ``status``: ``core`` (static rule), ``template`` (EMT/EPT/EET/EFT block), ``holding`` (a TPT
    position field, written with the TPT core rules) or ``custom`` (kept as custom attribute).
    """
    catalog = load_openfunds()
    core: dict[str, list[dict]] = {}
    for rule in STATIC_RULES:
        base = rule.field
        match = catalog.match_header(rule.field)
        if match is not None:
            base = match.of_id
        core.setdefault(base, []).append(_describe(rule))
    template: dict[str, list[dict]] = {}
    for tpl in templates():
        for f in tpl.fields:
            out = {"path": f"RegulatoryReportings/…/{tpl.element}/{f.path}", "template": tpl.name}
            if f.percent:
                out["transform"] = "openfunds decimal fraction (0.035) ↔ FundsXML percent (3.5)"
            template.setdefault(f.of_id, []).append(out)
    holding = {p.of_id: [p.tpt] for p in field_pairs()}
    for col, code in INSTRUMENT_IDS + UNDERLYING_IDS:
        holding[col] = ["14", f"15 = {code}"] if (col, code) in INSTRUMENT_IDS else ["68", f"69 = {code}"]
    holding[OTHER_ID] = ["14", "15 = 9 / 99"]
    holding[ISSUER_LEI] = ["47", "48 = 1"]
    fields = []
    for f in catalog.fields:
        if not f.active:
            continue
        entry = {
            "key": f.of_id,
            "name": f.name,
            "level": f.level,
            "tags": list(f.tags),
            "type": f.data_type,
            "definition": f.description[:400],
            "core": core.get(f.of_id, []),
            "template": template.get(f.of_id, []),
            "holding": holding.get(f.of_id, []),
        }
        entry["status"] = (
            "core"
            if entry["core"]
            else "template"
            if entry["template"]
            else "holding"
            if entry["holding"]
            else "custom"
        )
        fields.append(entry)
    return {"version": catalog.version, "date": catalog.date, "fields": fields}


def _describe(rule) -> dict:
    prefix = _CTX_PREFIX.get(rule.ctx) or _OF_PREFIX[rule.ctx == OF_FUND]
    out = {"path": prefix + rule.path}
    if rule.when_text:
        out["when"] = rule.when_text
    if rule.transform.name != "identity":
        out["transform"] = rule.transform.note or rule.transform.name
    return out


@router.get("/mapping/{version}")
async def mapping(version: str, response: Response) -> dict:
    v = version.upper()
    if v == "OPENFUNDS":
        response.headers["Cache-Control"] = "public, max-age=3600"
        emit("mapping_view", source="openfunds", status_code=200, status="ok")
        return openfunds_mapping_table()
    if v not in VERSIONS:
        raise HTTPException(404, "unknown TPT version")
    response.headers["Cache-Control"] = "public, max-age=3600"
    emit("mapping_view", tpt_version=v, status_code=200, status="ok")
    return mapping_table(v)
