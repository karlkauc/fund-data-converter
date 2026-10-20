"""XSD validation of generated FundsXML documents (libxml2 via lxml)."""

from __future__ import annotations

import threading
from functools import lru_cache

from lxml import etree

from app.schema.model import FUNDSXML_XSD

MAX_ERRORS = 200
_lock = threading.Lock()


@lru_cache(maxsize=1)
def fundsxml_schema() -> etree.XMLSchema:
    parser = etree.XMLParser(no_network=True, resolve_entities=False, load_dtd=False)
    return etree.XMLSchema(etree.parse(str(FUNDSXML_XSD), parser))


def validate_fundsxml(root: etree._Element) -> tuple[bool, list[str]]:
    schema = fundsxml_schema()
    # An XMLSchema object keeps its error log per call; serialise use across threads.
    with _lock:
        ok = schema.validate(root)
        errors = (
            [] if ok else [f"{_short_path(e.path)}: {e.message}" for e in list(schema.error_log)[:MAX_ERRORS]]
        )
    return ok, errors


def _short_path(path: str | None) -> str:
    # "/FundsXML4/Funds/Fund[2]/…" → drop the root for readability
    return (path or "").removeprefix("/FundsXML4")
