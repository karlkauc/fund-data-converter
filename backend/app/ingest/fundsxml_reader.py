"""Hardened parsing of uploaded FundsXML documents.

FundsXML never needs a DTD, so any DOCTYPE is rejected outright; with that,
external entities (XXE) and entity-expansion bombs are impossible. The
parser additionally forbids network access and keeps lxml's huge-tree
protection on.
"""

from __future__ import annotations

import re

from lxml import etree

_DOCTYPE = re.compile(rb"<!\s*(DOCTYPE|ENTITY)", re.IGNORECASE)


class FundsXmlReadError(ValueError):
    pass


def make_parser() -> etree.XMLParser:
    return etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        dtd_validation=False,
        huge_tree=False,
        remove_comments=True,
        remove_pis=True,
        remove_blank_text=True,
    )


def parse_fundsxml(data: bytes) -> etree._Element:
    if _DOCTYPE.search(data[:65536]) or _DOCTYPE.search(data):
        raise FundsXmlReadError("documents with a DOCTYPE or entity declarations are not accepted")
    try:
        root = etree.fromstring(data, make_parser())
    except etree.XMLSyntaxError as exc:
        raise FundsXmlReadError(f"not well-formed XML: {exc}") from exc
    if etree.QName(root).localname != "FundsXML4":
        raise FundsXmlReadError(f"root element is {etree.QName(root).localname}, expected FundsXML4")
    if etree.QName(root).namespace:
        _strip_namespaces(root)
    return root


def _strip_namespaces(root: etree._Element) -> None:
    # FundsXML 4 has no target namespace; tolerate files that declare a default one anyway.
    for el in root.iter():
        if isinstance(el.tag, str) and el.tag.startswith("{"):
            el.tag = etree.QName(el).localname
    etree.cleanup_namespaces(root)
