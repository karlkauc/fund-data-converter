"""The bundled example files (tools/make_samples.py): served, convertible in every direction, and
together covering the conditional mapping rules."""

from __future__ import annotations

import re

import pytest
from conftest import SAMPLES as SAMPLE_DIR

from app.api.samples import SAMPLES
from app.ingest.fundsxml_reader import parse_fundsxml
from app.ingest.openfunds_reader import read_openfunds
from app.ingest.tpt_reader import read_tpt
from app.mapping.openfunds_rules import STATIC_RULES
from app.mapping.rules import CORE_RULES
from app.service import FORMATS, Request, convert, detect_kind

FILES = {name: filename for name, (filename, _) in SAMPLES.items()}
CLEAN = [name for name in SAMPLES if not name.endswith("-errors")]
ERRORS = [name for name in SAMPLES if name.endswith("-errors")]
# Static data only: these share classes have no holdings, so there is no TPT to make of them.
NO_HOLDINGS = {"LU2900GMA027", "LU2900GMA035", "IE000DEMO507"}


def _bytes(name: str) -> bytes:
    return (SAMPLE_DIR / FILES[name]).read_bytes()


def test_every_file_is_served():
    assert sorted(FILES.values()) == sorted(p.name for p in SAMPLE_DIR.iterdir())


def test_source_format_matches_the_name():
    for name, filename in FILES.items():
        assert detect_kind(_bytes(name), filename) == name.split("-")[0], name


def test_download_is_counted_apart(client, monkeypatch):
    seen = []
    monkeypatch.setattr("app.api.samples.emit", lambda *a, **kw: seen.append(kw["source"]))
    r = client.get("/api/samples/openfunds-zip?download=1")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    assert 'filename="openfunds_csv.zip"' in r.headers["content-disposition"]
    assert client.get("/api/samples/tpt-csv").headers["content-type"].startswith("text/csv")
    assert seen == ["openfunds-zip:download", "tpt-csv"]


def _targets(name: str) -> list[str]:
    source = name.split("-")[0]
    return [f for f in FORMATS if f != source]


@pytest.mark.parametrize("name", CLEAN)
def test_clean_samples_convert_without_errors(name):
    for target in _targets(name):
        report, _ = convert(Request(_bytes(name), FILES[name], target=target))
        errors = [i["message"] for i in report["issues"] if i["level"] == "error"]
        assert errors == [], (target, errors)
        if target == "fundsxml":
            assert report["validation"]["valid"], (target, report["validation"]["errors"][:3])
        skipped = {
            i["params"]["shareclass"] for i in report["issues"] if i["code"] == "shareclass_no_portfolio"
        }
        assert skipped <= NO_HOLDINGS, target


@pytest.mark.parametrize("name", ERRORS)
def test_error_samples_are_reported(name):
    report, _ = convert(Request(_bytes(name), FILES[name]))
    codes = {i["code"] for i in report["issues"] if i["level"] in ("error", "warning")}
    assert len(codes) >= 3, codes


def test_fund_portfolio_sample():
    """One fund whose three share classes share the fund portfolio, one fund without share classes."""
    root = parse_fundsxml(_bytes("fundsxml-fund-portfolio"))
    a, b = root.findall("Funds/Fund")
    assert len(a.findall("SingleFund/ShareClasses/ShareClass")) == 3
    assert a.find("SingleFund/ShareClasses/ShareClass/Portfolios") is None
    assert a.find("FundDynamicData/Portfolios/Portfolio") is not None
    assert b.find("SingleFund") is None and b.find("FundDynamicData/Portfolios/Portfolio") is not None
    report, _ = convert(Request(_bytes("fundsxml-fund-portfolio"), "f.xml"))
    assert report["summary"]["portfolios"] == 4


# -- coverage of the conditional mapping rules ---------------------------------------------

TPT_SAMPLES = ("tpt-v7", "tpt-v8", "tpt-all-cic", "tpt-multi")
OF_SAMPLES = ("openfunds", "openfunds-multi", "openfunds-static", "openfunds-zip")
# Rules no sample exercises, with the reason.
TPT_UNCOVERED = {
    # Portfolio code types other than ISIN: the same rules as the position identifiers (14/15), which
    # cover every type; openfunds keys share classes by ISIN, so the samples keep ISINs.
    *((("1", f"2 = {t}")) for t in ("2", "3", "4", "5", "6", "7", "8", "9", "99")),
}
OF_UNCOVERED = {
    "OFST710102",  # master fund ISIN: feeder funds only
}


def test_tpt_samples_cover_the_core_rules():
    rows = [r.values for n in TPT_SAMPLES for r in read_tpt(_bytes(n), FILES[n]).rows]
    missing = {
        (rule.field, rule.when_text)
        for rule in CORE_RULES
        # "fund without share classes" rules are read from FundsXML (fundsxml-fund-portfolio)
        if not rule.read_only and rule.ctx not in ("fund", "nav")
        if not any(rule.applies(r) and r.get(rule.field) for r in rows)
    }
    assert missing == TPT_UNCOVERED


def _family(field: str, when_text: str) -> tuple[str, str]:
    """Registration rules per country are one rule family: OFST6030LU and OFST6030AT are alike."""
    m = re.fullmatch(r"(OFST60\d\d)([A-Z]{2})", field)
    return (m[1], when_text.replace(m[2], "XX")) if m else (field, when_text)


def test_openfunds_samples_cover_the_static_rules():
    records = [r.values for n in OF_SAMPLES for r in read_openfunds(_bytes(n), FILES[n]).shareclasses]
    covered = {
        _family(rule.field, rule.when_text)
        for rule in STATIC_RULES
        if any(rule.applies(r) and r.get(rule.field) for r in records)
    }
    missing = {_family(r.field, r.when_text) for r in STATIC_RULES} - covered
    assert {field for field, _ in missing} == OF_UNCOVERED
