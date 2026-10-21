"""GET /api/mapping/{version} – the field mapping table (static, cacheable)."""

from __future__ import annotations

from functools import lru_cache

from fastapi import APIRouter, HTTPException, Response

from app.mapping.rules import BLOCK_RULES, CORE_RULES
from app.spec.catalog import VERSIONS, load_catalog
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


def _describe(rule) -> dict:
    out = {"path": _CTX_PREFIX[rule.ctx] + rule.path}
    if rule.when_text:
        out["when"] = rule.when_text
    if rule.transform.name != "identity":
        out["transform"] = rule.transform.note or rule.transform.name
    return out


@router.get("/mapping/{version}")
async def mapping(version: str, response: Response) -> dict:
    v = version.upper()
    if v not in VERSIONS:
        raise HTTPException(404, "unknown TPT version")
    response.headers["Cache-Control"] = "public, max-age=3600"
    emit("mapping_view", tpt_version=v, status_code=200, status="ok")
    return mapping_table(v)
