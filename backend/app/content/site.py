"""Per-site constants for the content pages; the rest of ``app.content`` is shared with the siblings."""

from __future__ import annotations

SITE_NAME = "TPT ⇄ FundsXML Converter"
# Where the "Open the converter" button in the page header points.
VIEWER_PATH = "/"
OPEN_LABEL = "Open the converter"
LOGO_PATH = "/favicon.svg"
# Preview image for shared links, 1200×630 (frontend/public); index.html names the same.
OG_IMAGE_PATH = "/og-image.png"
OG_IMAGE_ALT = "TPT ⇄ FundsXML Converter — FinDatEx Tripartite Template to FundsXML 4 and back"
# This site's key in FAMILY; its own entry is shown without a link.
SELF = "tpt"

# Same list, same order on all sites of the family. Sister links go through /go/
# so clicks are counted without client-side tracking.
FAMILY: tuple[tuple[str, str, str], ...] = (
    ("xsd", "XSD Viewer", "/go/xsd-viewer"),
    ("xml", "XML Viewer", "/go/xml-viewer"),
    ("odata", "OData Viewer", "/go/odata-viewer"),
    ("tpt", "TPT Converter", "/go/tpt-converter"),
    ("desktop", "Desktop app", "/go/freexmltoolkit"),
)

# /guides lists these sections in this order (app/content/pages.py, _hub). A prefix
# ending in "/" takes every page below it; pages in no section are not listed.
# The single field pages are linked from tpt/fields.
HUB_INTRO = (
    "Guides for the FinDatEx Tripartite Template (TPT) and FundsXML: what TPT is, what changed in V8, "
    "how each TPT field maps to FundsXML 4, and how to automate the conversion."
)
HUB_SECTIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Tripartite Template", ("guides/what-is-tpt", "guides/tpt-v7-vs-v8", "guides/tpt-file-format")),
    (
        "Conversion",
        ("guides/tpt-to-fundsxml", "guides/fundsxml-to-tpt", "guides/automate-tpt-conversion"),
    ),
    ("Reference", ("tpt/fields", "tpt/issues")),
)
