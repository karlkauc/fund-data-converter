from collections import Counter

from app.spec.openfunds import load_openfunds


def test_catalog_size_and_prefixes():
    cat = load_openfunds()
    assert cat.version == "2.13.0"
    assert len(cat.fields) == len(cat.by_id) == 1869
    prefixes = Counter(f.prefix for f in cat.fields)
    assert prefixes["OFST"] == 652
    assert prefixes["OFPH"] == 92
    assert prefixes["OFEE"] == 617
    assert all(f.data_type in {"string", "double", "boolean", "date", "integer", "time"} for f in cat.fields)


def test_field_details():
    cat = load_openfunds()
    isin = cat.by_id["OFST020000"]
    assert isin.name == "ISIN" and isin.level == "Share Class"
    policy = cat.by_id["OFST020400"]
    assert policy.codes == ("accumulating", "accumulating & distributing", "distributing")
    assert cat.by_id["OFST6010XX"].country_pattern


def test_findatex_references():
    cat = load_openfunds()
    weight = cat.by_id["OFPH000300"].ref("TPT")
    assert weight and weight.num == "26"
    assert cat.by_id["OFEM000010"].ref("EMT").num == "00001"
    templates = Counter(r.template for f in cat.fields for r in f.findatex)
    assert templates["EET"] >= 617 and templates["TPT"] >= 68


def test_match_header():
    cat = load_openfunds()
    assert cat.match_header("OFST020000").of_id == "OFST020000"
    assert cat.match_header("OFST020000 ISIN").of_id == "OFST020000"
    tagged = cat.match_header("OFST001000(zh-Hant)")
    assert tagged.of_id == "OFST001000" and tagged.language == "zh-Hant"
    country = cat.match_header("OFST6010AT")
    assert country.of_id == "OFST6010XX" and country.country == "AT" and country.column == "OFST6010AT"
    assert cat.match_header("12_CIC_code") is None
    assert cat.match_name("Share Class Currency") == "OFST020540"
