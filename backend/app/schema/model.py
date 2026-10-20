"""A compact, query-friendly model of the bundled FundsXML XSD.

The writer needs three things from the schema that lxml's validator does not
expose: the declared order of child elements, which children are required
(and which belong to a choice), and the facets of simple types (enumerations,
patterns, base type) so values can be normalised before they are written.

The model is built once from the XSD, starting at the root element, and the
parsed XSD tree is dropped afterwards; only the types reachable from the root
are kept.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from lxml import etree

XS = "{http://www.w3.org/2001/XMLSchema}"
SCHEMA_DIR = Path(__file__).resolve().parent
FUNDSXML_XSD = SCHEMA_DIR / "FundsXML4.xsd"

UNBOUNDED = -1


@dataclass(frozen=True)
class SimpleType:
    """Facets of a simple type, flattened along its restriction chain."""

    base: str  # XSD built-in local name: string, decimal, date, boolean, int, ...
    enums: tuple[str, ...] = ()
    patterns: tuple[str, ...] = ()
    min_length: int | None = None
    max_length: int | None = None

    @property
    def compiled_patterns(self) -> tuple[re.Pattern[str], ...]:
        return _compile_patterns(self.patterns)


@lru_cache(maxsize=512)
def _compile_patterns(patterns: tuple[str, ...]) -> tuple[re.Pattern[str], ...]:
    out = []
    for p in patterns:
        try:
            out.append(re.compile(_xsd_regex_to_python(p)))
        except re.error:
            continue  # an XSD-only construct; the final XSD validation still checks it
    return tuple(out)


def _xsd_regex_to_python(p: str) -> str:
    # XSD's \i / \c name classes have no Python counterpart; approximate them.
    return p.replace(r"\i", r"[A-Za-z_:]").replace(r"\c", r"[-.\w:]")


STRING = SimpleType("string")


@dataclass(frozen=True)
class Attribute:
    name: str
    simple: SimpleType
    required: bool


@dataclass
class ElementDecl:
    name: str
    type_key: str | None  # key into SchemaModel.complex; None for simple content
    simple: SimpleType | None  # set for simple elements
    min_occurs: int
    max_occurs: int  # UNBOUNDED = -1
    choice: tuple[int, int] | None = None  # (choice group id, branch index)
    order: int = 0


@dataclass
class ChoiceGroup:
    id: int
    min_occurs: int


@dataclass
class ComplexType:
    key: str
    children: list[ElementDecl] = field(default_factory=list)
    attributes: dict[str, Attribute] = field(default_factory=dict)
    simple_content: SimpleType | None = None  # complexType/simpleContent/extension
    choices: dict[int, ChoiceGroup] = field(default_factory=dict)

    def child(self, name: str) -> ElementDecl | None:
        return self._index().get(name)

    def _index(self) -> dict[str, ElementDecl]:
        idx = self.__dict__.get("_idx")
        if idx is None:
            idx = {}
            for decl in self.children:
                idx.setdefault(decl.name, decl)
            self.__dict__["_idx"] = idx
        return idx


class SchemaModel:
    def __init__(self, root_element: str, root: ElementDecl, complex_types: dict[str, ComplexType]):
        self.root_element = root_element
        self.root = root
        self.complex = complex_types

    def type_at(self, path: list[str]) -> ComplexType | None:
        """Complex type of the element at ``path`` (names from the root, root excluded)."""
        ct = self.complex.get(self.root.type_key or "")
        for name in path:
            if ct is None:
                return None
            decl = ct.child(name)
            if decl is None or decl.type_key is None:
                return None
            ct = self.complex[decl.type_key]
        return ct

    def decl_at(self, path: list[str]) -> ElementDecl | None:
        if not path:
            return self.root
        parent = self.type_at(path[:-1])
        return parent.child(path[-1]) if parent else None


class _Builder:
    def __init__(self, xsd_path: Path):
        parser = etree.XMLParser(no_network=True, resolve_entities=False, load_dtd=False)
        doc = etree.parse(str(xsd_path), parser).getroot()
        self.ctypes = {e.get("name"): e for e in doc.findall(XS + "complexType")}
        self.stypes = {e.get("name"): e for e in doc.findall(XS + "simpleType")}
        self.elements = {e.get("name"): e for e in doc.findall(XS + "element")}
        self.groups = {e.get("name"): e for e in doc.findall(XS + "group")}
        self.attr_groups = {e.get("name"): e for e in doc.findall(XS + "attributeGroup")}
        self.out: dict[str, ComplexType] = {}
        self._simple_cache: dict[str, SimpleType] = {}
        self._anon = 0
        self._choice_seq = 0

    # -- simple types -------------------------------------------------------
    def simple(self, type_name: str | None, inline: etree._Element | None = None) -> SimpleType:
        if inline is not None:
            return self._simple_from_node(inline)
        if not type_name:
            return STRING
        local = type_name.split(":")[-1]
        if type_name.startswith("xs:") or local not in self.stypes:
            return SimpleType(local)
        if local not in self._simple_cache:
            self._simple_cache[local] = self._simple_from_node(self.stypes[local])
        return self._simple_cache[local]

    def _simple_from_node(self, st: etree._Element) -> SimpleType:
        restriction = st.find(XS + "restriction")
        if restriction is None:
            return STRING  # list / union: treat as text
        base_name = restriction.get("base")
        inner = restriction.find(XS + "simpleType")
        base = self.simple(base_name, inner) if (base_name or inner is not None) else STRING
        enums = tuple(e.get("value") for e in restriction.findall(XS + "enumeration"))
        patterns = tuple(e.get("value") for e in restriction.findall(XS + "pattern"))

        def facet(name: str) -> int | None:
            node = restriction.find(XS + name)
            return int(node.get("value")) if node is not None else None

        length = facet("length")
        return SimpleType(
            base=base.base,
            enums=enums or base.enums,
            patterns=patterns + base.patterns,
            min_length=length if length is not None else (facet("minLength") or base.min_length),
            max_length=length if length is not None else (facet("maxLength") or base.max_length),
        )

    # -- complex types ------------------------------------------------------
    def complex_key(self, type_name: str | None, inline: etree._Element | None) -> str | None:
        if inline is not None:
            self._anon += 1
            key = f"#anon{self._anon}"
            self.out[key] = ComplexType(key)
            self._fill(self.out[key], inline)
            return key
        local = (type_name or "").split(":")[-1]
        if local not in self.ctypes:
            return None
        if local not in self.out:
            self.out[local] = ComplexType(local)
            self._fill(self.out[local], self.ctypes[local])
        return local

    def _fill(self, ct: ComplexType, node: etree._Element) -> None:
        simple_content = node.find(XS + "simpleContent")
        if simple_content is not None:
            ext = simple_content.find(XS + "extension")
            if ext is None:
                ext = simple_content.find(XS + "restriction")
            if ext is not None:
                base = ext.get("base")
                local = (base or "").split(":")[-1]
                if local in self.ctypes:
                    base_ct = self.out[self.complex_key(local, None)]
                    ct.simple_content = base_ct.simple_content
                    ct.attributes.update(base_ct.attributes)
                else:
                    ct.simple_content = self.simple(base)
                self._attributes(ct, ext)
            return
        complex_content = node.find(XS + "complexContent")
        if complex_content is not None:
            ext = complex_content.find(XS + "extension")
            if ext is None:
                ext = complex_content.find(XS + "restriction")
            if ext is not None:
                base_key = self.complex_key(ext.get("base"), None)
                if base_key and ext.tag == XS + "extension":
                    base_ct = self.out[base_key]
                    ct.children.extend(base_ct.children)
                    ct.attributes.update(base_ct.attributes)
                    ct.choices.update(base_ct.choices)
                self._particles(ct, ext, None)
                self._attributes(ct, ext)
            for i, decl in enumerate(ct.children):
                decl.order = i
            return
        self._particles(ct, node, None)
        self._attributes(ct, node)
        for i, decl in enumerate(ct.children):
            decl.order = i

    def _attributes(self, ct: ComplexType, node: etree._Element) -> None:
        for a in node.findall(XS + "attribute"):
            name = a.get("name") or a.get("ref")
            if not name:
                continue
            ct.attributes[name] = Attribute(
                name, self.simple(a.get("type"), a.find(XS + "simpleType")), a.get("use") == "required"
            )
        for g in node.findall(XS + "attributeGroup"):
            ref = self.attr_groups.get((g.get("ref") or "").split(":")[-1])
            if ref is not None:
                self._attributes(ct, ref)

    def _particles(self, ct: ComplexType, node: etree._Element, choice: tuple[int, int] | None) -> None:
        for child in node:
            tag = child.tag
            if tag == XS + "element":
                ct.children.append(self._element(child, choice))
            elif tag in (XS + "sequence", XS + "all"):
                if choice is not None and child.getparent().tag == XS + "choice":
                    branch = (choice[0], list(child.getparent()).index(child))
                    self._particles(ct, child, branch)
                else:
                    self._particles(ct, child, choice)
            elif tag == XS + "choice":
                self._choice_seq += 1
                cid = self._choice_seq
                ct.choices[cid] = ChoiceGroup(cid, int(child.get("minOccurs", "1")))
                for idx, branch in enumerate(child):
                    if branch.tag == XS + "element":
                        ct.children.append(self._element(branch, (cid, idx)))
                    elif branch.tag in (XS + "sequence", XS + "all", XS + "choice", XS + "group"):
                        wrapper = etree.Element(XS + "sequence")
                        wrapper.append(_shallow_copy(branch))
                        self._particles(ct, wrapper, (cid, idx))
            elif tag == XS + "group" and child.get("ref"):
                group = self.groups.get(child.get("ref").split(":")[-1])
                if group is not None:
                    self._particles(ct, group, choice)

    def _element(self, node: etree._Element, choice: tuple[int, int] | None) -> ElementDecl:
        min_occurs = int(node.get("minOccurs", "1"))
        max_raw = node.get("maxOccurs", "1")
        max_occurs = UNBOUNDED if max_raw == "unbounded" else int(max_raw)
        ref = node.get("ref")
        target = node
        name = node.get("name")
        if ref:
            name = ref
            target = self.elements.get(ref.split(":")[-1], node)
        type_name = target.get("type")
        inline_ct = target.find(XS + "complexType")
        inline_st = target.find(XS + "simpleType")
        type_key = self.complex_key(type_name, inline_ct)
        simple = None
        if type_key is None:
            simple = self.simple(type_name, inline_st)
        return ElementDecl(name, type_key, simple, min_occurs, max_occurs, choice)


def _shallow_copy(node: etree._Element) -> etree._Element:
    return etree.fromstring(etree.tostring(node))


@lru_cache(maxsize=1)
def fundsxml_model() -> SchemaModel:
    builder = _Builder(FUNDSXML_XSD)
    root_el = builder.elements["FundsXML4"]
    root = builder._element(root_el, None)
    return SchemaModel("FundsXML4", root, builder.out)
