"""Search-engine surface: shell metadata, content pages, sitemap, robots, redirects, headers."""

from __future__ import annotations

import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import spa
from app.config import settings
from app.content.fields import field_pages
from app.content.openfunds_fields import openfunds_field_pages
from app.content.pages import all_pages, register_provider

SHELL = """<!doctype html><html><head>
<title>x</title>
<meta name="description" content="x" />
<link rel="canonical" href="https://www.fund-data-converter.eu/" />
<meta property="og:title" content="x" />
<meta property="og:description" content="x" />
<meta property="og:url" content="https://www.fund-data-converter.eu/" />
<meta property="og:image" content="https://www.fund-data-converter.eu/og-image.png" />
<!--faq-jsonld-->
</head><body><div id="root"><!--faq--></div></body></html>"""


@pytest.fixture(scope="module", autouse=True)
def _field_pages():
    # app.main registers the provider; make sure it is there when this module runs alone.
    if not any(slug.startswith("tpt/fields/") for slug in all_pages()):
        register_provider(field_pages)
    if not any(slug.startswith("openfunds/fields/") for slug in all_pages()):
        register_provider(openfunds_field_pages)


@pytest.fixture
def site(tmp_path, monkeypatch):
    monkeypatch.setattr(spa, "emit", lambda *a, **k: True)
    monkeypatch.setattr(settings, "site_origin", "https://tpt.example")
    (tmp_path / "index.html").write_text(SHELL, encoding="utf-8")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "index-abc123.js").write_text("console.log(1)", encoding="utf-8")
    app = FastAPI()
    spa.mount_spa(app, tmp_path)
    with TestClient(app) as c:
        yield c


def test_shell_has_canonical_og_and_home_faq(site):
    home = site.get("/").text
    assert '<link rel="canonical" href="https://tpt.example/" />' in home
    assert 'og:image" content="https://tpt.example/og-image.png"' in home
    assert "www.fund-data-converter.eu" not in home
    assert '"@type": "FAQPage"' in home and '<details class="faq">' in home
    mapping = site.get("/mapping").text
    assert '<link rel="canonical" href="https://tpt.example/mapping" />' in mapping
    assert '<meta property="og:url" content="https://tpt.example/mapping" />' in mapping
    assert "FAQPage" not in mapping and "<!--faq" not in mapping
    assert f"<title>{spa.ROUTE_META['mapping'].title}</title>" in mapping


def test_trailing_slash_redirects_and_keeps_the_query(site):
    r = site.get("/mapping/?utm_source=x", follow_redirects=False)
    assert r.status_code == 301 and r.headers["location"] == "/mapping?utm_source=x"
    assert site.get("/guides/", follow_redirects=False).headers["location"] == "/guides"
    assert site.get("/nope/", follow_redirects=False).status_code == 404


def test_content_pages_render_with_breadcrumbs_and_article(site):
    r = site.get("/tpt/fields/12-cic-code-of-the-instrument")
    assert r.status_code == 200
    assert "<h1>TPT field 12 – CIC code of the instrument</h1>" in r.text
    assert '"@type": "TechArticle"' in r.text and '"@type": "BreadcrumbList"' in r.text
    assert (
        '<link rel="canonical" href="https://tpt.example/tpt/fields/12-cic-code-of-the-instrument" />'
        in r.text
    )
    assert "/go/xsd-viewer" in r.text  # family footer
    api = site.get("/guides/automate-tpt-conversion").text
    assert "https://tpt.example/api/convert" in api and "{{origin}}" not in api


def test_every_internal_link_of_the_content_pages_resolves(site):
    known = {f"/{route}" for route in spa.ROUTE_META} | {f"/{slug}" for slug in all_pages()}
    known |= {"/api/docs", "/content.css", "/favicon.svg"}
    broken = set()
    for slug in all_pages():
        for href in re.findall(r'href="(/[^"#?]*)', site.get(f"/{slug}").text):
            if href not in known and not href.startswith("/go/"):
                broken.add((slug, href))
    assert not broken


def test_sitemap_lists_routes_and_every_field(site):
    xml = site.get("/sitemap.xml")
    assert xml.headers["content-type"].startswith("application/xml")
    locs = re.findall(r"<loc>([^<]+)</loc>", xml.text)
    assert "https://tpt.example/" in locs and "https://tpt.example/api-docs" in locs
    assert "https://tpt.example/tpt/fields/1000-tpt-version" in locs
    assert sum(loc.startswith("https://tpt.example/tpt/fields/") for loc in locs) == 154  # TPT V8
    assert "https://tpt.example/tpt/fields" in locs
    assert "https://tpt.example/openfunds/fields/ofst020000-isin" in locs
    assert "https://tpt.example/openfunds/fields" in locs
    assert "https://tpt.example/openfunds-to-fundsxml" in locs
    assert len(locs) == len(set(locs))


def test_robots_and_llms_name_the_configured_origin(site):
    robots = site.get("/robots.txt").text
    assert "Disallow: /api/" in robots and "Sitemap: https://tpt.example/sitemap.xml" in robots
    llms = site.get("/llms.txt").text
    assert llms.startswith("# Fund Data Converter")
    assert "https://tpt.example/guides/what-is-tpt" in llms


def test_hashed_assets_are_cached_for_a_year(site):
    r = site.get("/assets/index-abc123.js")
    assert r.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert site.get("/").headers["cache-control"] == "no-cache"


def test_indexnow_key_file(site, monkeypatch):
    assert site.get("/k123.txt").status_code == 404
    monkeypatch.setattr(settings, "indexnow_key", "k123")
    assert site.get("/k123.txt").text == "k123"


def test_other_hosts_are_not_indexed(client):
    assert "x-robots-tag" not in client.get("/api/health").headers
    r = client.get("/api/health", headers={"host": "tpt-fundsxml-abc-ew.a.run.app"})
    assert r.headers["x-robots-tag"] == "noindex"


def test_go_redirects_to_sisters_with_utm(client):
    r = client.get("/go/xsd-viewer", follow_redirects=False)
    assert r.status_code == 302
    assert (
        r.headers["location"] == "https://www.xsd-viewer.online/?utm_source=tpt-converter&utm_medium=sister"
    )
    assert (
        client.get("/go/freexmltoolkit?to=releases", follow_redirects=False)
        .headers["location"]
        .endswith("/FreeXmlToolkit/releases")
    )
    assert client.get("/go/elsewhere", follow_redirects=False).status_code == 404


def test_faq_api_and_gzip(client):
    r = client.get("/api/content/faq", headers={"accept-encoding": "gzip"})
    assert r.status_code == 200 and r.headers["content-encoding"] == "gzip"
    faq = r.json()
    assert faq[0]["question"] == "What does the Fund Data Converter do?"
    assert faq[0]["answer_html"].startswith("<p>")
