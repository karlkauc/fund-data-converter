"""Schema-guided XML building.

Mappings write values into a loose :class:`Node` tree by path, in any order.
:func:`serialize` then turns the tree into lxml elements using the schema
model: children are emitted in declared order, values are normalised to their
simple type (or dropped when they cannot be), and optional subtrees that lack
a required child are pruned instead of producing an invalid document. Every
dropped value is reported with the TPT field it came from, so the converter
can keep it elsewhere and tell the user.

Path syntax (``/``-separated segments)::

    Name                       child element
    Name[Child=value]          child whose sub-element Child has text value
    Name[@attr=value]          child with attribute value
    @attr                      attribute of the current element (last segment only)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from functools import lru_cache

from lxml import etree

from app.schema.model import UNBOUNDED, ComplexType, ElementDecl, SchemaModel, SimpleType

_SEGMENT = re.compile(r"^(?P<name>@?[A-Za-z_][\w.\-]*)(?:\[(?P<pred>@?[\w.\-]+)=(?P<val>[^\]]*)\])?$")


@dataclass
class Dropped:
    """A value that did not make it into the document."""

    path: str
    value: str
    reason: str
    origins: tuple[str, ...]  # TPT field keys (numKey) whose values were lost


Segment = tuple[str, str | None, str]  # (name, predicate, predicate value)


class Node:
    """A loosely built XML element; slots keep large trees (tens of thousands of positions) small."""

    __slots__ = ("name", "text", "attrs", "children", "origin", "attr_origins")

    def __init__(self, name: str, text: str | None = None):
        self.name = name
        self.text = text
        self.attrs: dict[str, str] = {}
        self.children: list[Node] = []
        self.origin: str | None = None  # origin tag of the TPT value that set ``text``
        self.attr_origins: dict[str, str] = {}

    # -- building ---------------------------------------------------------
    def child(self, name: str) -> Node | None:
        for c in self.children:
            if c.name == name:
                return c
        return None

    def add(self, name: str) -> Node:
        node = Node(name)
        self.children.append(node)
        return node

    def ensure(self, path: str) -> Node:
        node = self
        for seg in _parse(path):
            node = node._ensure_segment(seg)
        return node

    def _ensure_segment(self, seg: Segment) -> Node:
        name, pred, val = seg
        for c in self.children:
            if c.name == name and (pred is None or c._matches(pred, val)):
                return c
        node = self.add(name)
        if pred is not None:
            if pred.startswith("@"):
                node.attrs[pred[1:]] = val
            else:
                node.add(pred).text = val
        return node

    def _matches(self, pred: str, val: str) -> bool:
        if pred.startswith("@"):
            return self.attrs.get(pred[1:]) == val
        sub = self.child(pred)
        return sub is not None and sub.text == val

    def set(self, path: str, value: str | None, origin: str | None = None, keep_empty: bool = False) -> None:
        """Write ``value`` at ``path``; empty values are ignored unless ``keep_empty``."""
        if value is None or (value == "" and not keep_empty):
            return
        segs = _parse(path)
        if segs and segs[-1][0].startswith("@"):
            target = self
            for seg in segs[:-1]:
                target = target._ensure_segment(seg)
            attr = segs[-1][0][1:]
            target.attrs[attr] = value
            if origin:
                target.attr_origins[attr] = origin
            return
        target = self
        for seg in segs:
            target = target._ensure_segment(seg)
        target.text = value
        target.origin = origin

    def find(self, path: str) -> Node | None:
        node: Node | None = self
        for name, pred, val in _parse(path):
            if node is None:
                return None
            node = next(
                (c for c in node.children if c.name == name and (pred is None or c._matches(pred, val))),
                None,
            )
        return node

    def origins(self) -> tuple[str, ...]:
        found: list[str] = []
        stack = [self]
        while stack:
            n = stack.pop()
            if n.origin and n.text is not None:
                found.append(n.origin)
            found.extend(n.attr_origins.values())
            stack.extend(n.children)
        return tuple(dict.fromkeys(found))


@lru_cache(maxsize=4096)
def _parse(path: str) -> tuple[Segment, ...]:
    out = []
    for seg in _split(path):
        m = _SEGMENT.match(seg)
        if not m:
            raise ValueError(f"bad path segment {seg!r}")
        out.append((m.group("name"), m.group("pred"), m.group("val")))
    return tuple(out)


def _split(path: str) -> list[str]:
    # Split on "/" outside of [...] predicates.
    out, depth, cur = [], 0, []
    for ch in path:
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
        if ch == "/" and depth == 0:
            if cur:
                out.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    if cur:
        out.append("".join(cur).strip())
    return out


# ---------------------------------------------------------------------------
# Value normalisation
# ---------------------------------------------------------------------------

_DECIMAL_TYPES = {"decimal", "float", "double"}
_INT_TYPES = {
    "int",
    "integer",
    "long",
    "short",
    "byte",
    "nonNegativeInteger",
    "positiveInteger",
    "unsignedInt",
    "unsignedLong",
    "unsignedShort",
    "nonPositiveInteger",
    "negativeInteger",
}


def normalize(value: str, simple: SimpleType) -> str:
    """Return ``value`` in the lexical form of ``simple`` or raise ValueError."""
    v = value.strip()
    if not v:
        if simple.base == "string" and not (simple.enums or simple.patterns or simple.min_length):
            return ""
        raise ValueError("empty")
    base = simple.base
    if base in _DECIMAL_TYPES:
        v = format_decimal(parse_decimal(v))
    elif base in _INT_TYPES:
        d = parse_decimal(v)
        if d != d.to_integral_value():
            raise ValueError("not an integer")
        v = str(int(d))
    elif base == "date":
        v = parse_date(v).isoformat()
    elif base == "dateTime":
        v = parse_datetime(v)
    elif base == "boolean":
        low = v.lower()
        if low in ("true", "1", "y", "yes"):
            v = "true"
        elif low in ("false", "0", "n", "no"):
            v = "false"
        else:
            raise ValueError("not a boolean")
    if simple.enums:
        v = match_enum(v, simple.enums)
    if simple.max_length is not None and len(v) > simple.max_length:
        raise ValueError(f"longer than {simple.max_length} characters")
    if simple.min_length is not None and len(v) < simple.min_length:
        raise ValueError(f"shorter than {simple.min_length} characters")
    patterns = simple.compiled_patterns
    if patterns and not any(p.fullmatch(v) for p in patterns):
        raise ValueError("does not match the required format")
    return v


def match_enum(value: str, enums: tuple[str, ...]) -> str:
    if value in enums:
        return value
    low = value.lower()
    for e in enums:
        if e.lower() == low:
            return e
    # "1 - ISIN", "1: ISO 6166" → "1"
    head = re.split(r"\s*[-:–]\s*|\s+", value, maxsplit=1)[0]
    if head in enums:
        return head
    raise ValueError(f"not one of {', '.join(enums[:12])}{'…' if len(enums) > 12 else ''}")


def parse_decimal(v: str) -> Decimal:
    s = v.replace(" ", "").replace(" ", "").replace("'", "")
    if s.endswith("%"):
        raise ValueError("percent sign")
    if "," in s and "." in s:
        # The later separator is the decimal mark: 1.234,56 or 1,234.56
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".") if s.count(",") == 1 else s.replace(",", "")
    try:
        d = Decimal(s)
    except InvalidOperation as exc:
        raise ValueError("not a number") from exc
    if not d.is_finite():
        raise ValueError("not a number")
    return d


def format_decimal(d: Decimal) -> str:
    if d == 0:
        return "0"
    if d == d.to_integral_value() and abs(d) < Decimal("1e21"):
        return str(d.quantize(Decimal(1)))
    s = format(d, "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s if s not in ("-0", "") else "0"


_DATE_FORMATS = ("%Y-%m-%d", "%Y%m%d", "%d.%m.%Y", "%d/%m/%Y", "%Y/%m/%d", "%d-%m-%Y")


def parse_date(v: str) -> date:
    s = v.strip()
    if "T" in s or " " in s:
        s = re.split(r"[T ]", s, maxsplit=1)[0]
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise ValueError("not a date")


def parse_datetime(v: str) -> str:
    s = v.strip()
    try:
        return datetime.fromisoformat(s).isoformat()
    except ValueError:
        return datetime.combine(parse_date(s), datetime.min.time()).isoformat()


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------


class Serializer:
    """Build lxml elements from a :class:`Node` tree.

    A problem (missing required content, a value outside its type) makes the
    element *invalid*. Invalidity climbs to the nearest optional ancestor,
    which is then dropped as a whole and reported. Along a chain of required
    elements nothing is dropped: the element is kept and reported as invalid,
    because losing a whole portfolio over one missing mandatory value would be
    worse than an XSD error the user can see and fix at the source.
    """

    def __init__(self, model: SchemaModel):
        self.model = model
        self.dropped: list[Dropped] = []
        self.invalid: list[Dropped] = []
        self.sealed = 0  # invalid entries already contained by a list item

    def element(
        self, node: Node, decl: ElementDecl, path: str, required: bool | None = None
    ) -> tuple[etree._Element | None, bool]:
        """Return ``(element, is_invalid)``; element is None when dropped."""
        if required is None:
            required = decl.min_occurs >= 1
        mark, sealed_before = len(self.invalid), self.sealed
        if decl.type_key is None:
            el, problems = self._leaf(node, decl.simple, path)
        else:
            el, problems = self._complex(node, self.model.complex[decl.type_key], path)
        if problems:
            self.invalid.append(Dropped(path, node.text or "", "; ".join(problems), node.origins()))
        new_problems = (len(self.invalid) - mark) - (self.sealed - sealed_before)
        if new_problems == 0:
            return el, False
        if required and decl.type_key is not None and decl.max_occurs != 1:
            # A list item (Position, Asset, Fund, …) keeps its problems to itself: it is
            # kept and reported, and its container stays valid for the other items.
            self.sealed += new_problems
            return el, False
        if required:
            return el, True
        # Optional: drop the subtree and turn the collected problems into one report.
        reasons = list(dict.fromkeys(d.reason for d in self.invalid[mark:]))
        self.sealed = sealed_before
        del self.invalid[mark:]
        origins = node.origins()
        if origins or node.text:
            self.dropped.append(Dropped(path, node.text or "", "; ".join(reasons), origins))
        return None, False

    def _complex(self, node: Node, ct: ComplexType, path: str) -> tuple[etree._Element, list[str]]:
        el = etree.Element(node.name)
        problems: list[str] = []
        for name, value in node.attrs.items():
            attr = ct.attributes.get(name)
            if attr is None:
                self._drop(f"{path}/@{name}", value, "attribute not in schema", node.attr_origins.get(name))
                continue
            try:
                el.set(name, normalize(value, attr.simple))
            except ValueError as exc:
                self._drop(f"{path}/@{name}", value, str(exc), node.attr_origins.get(name))
        problems += [
            f"required attribute {n} missing"
            for n, a in ct.attributes.items()
            if a.required and el.get(n) is None
        ]

        if ct.simple_content is not None:
            if node.text is None:
                problems.append("value missing")
            else:
                try:
                    el.text = normalize(node.text, ct.simple_content)
                except ValueError as exc:
                    problems.append(str(exc))
                    el.text = node.text
            return el, problems

        built: list[tuple[int, int, etree._Element]] = []
        counts: dict[str, int] = {}
        seen: dict[str, int] = {}
        totals: dict[str, int] = {}
        for c in node.children:
            totals[c.name] = totals.get(c.name, 0) + 1
        branch_of_choice: dict[int, int] = {}
        for seq, child in enumerate(node.children):
            seen[child.name] = seen.get(child.name, 0) + 1
            decl = ct.child(child.name)
            cpath = f"{path}/{child.name}"
            if decl is None:
                self._drop_subtree(child, cpath, "element not in schema")
                continue
            if decl.max_occurs != UNBOUNDED and counts.get(child.name, 0) >= decl.max_occurs:
                self._drop_subtree(child, cpath, "element repeated too often")
                continue
            if decl.choice is not None:
                chosen = branch_of_choice.get(decl.choice[0])
                if chosen is not None and chosen != decl.choice[1]:
                    self._drop_subtree(child, cpath, "conflicts with another choice branch")
                    continue
            required = None
            if decl.type_key is None or self.model.complex[decl.type_key].simple_content is not None:
                # A repeated value element (e.g. Amount per currency) is only required
                # while no further sibling can satisfy the minimum.
                later = seen[child.name] < totals[child.name]
                required = decl.min_occurs > counts.get(child.name, 0) and not later
            sub, _bad = self.element(child, decl, cpath, required)
            if sub is None:
                continue
            if decl.choice is not None:
                branch_of_choice[decl.choice[0]] = decl.choice[1]
            counts[child.name] = counts.get(child.name, 0) + 1
            built.append((decl.order, seq, sub))

        for decl in ct.children:
            if decl.min_occurs < 1 or decl.name in counts:
                continue
            if decl.choice is not None:
                cid, branch = decl.choice
                group = ct.choices.get(cid)
                chosen = branch_of_choice.get(cid)
                if chosen is not None and chosen != branch:
                    continue
                if chosen is None and (group is None or group.min_occurs < 1):
                    continue
                if chosen is None:
                    problems.append("required choice missing")
                    continue
            empty = self._empty_element(decl)
            if empty is not None:
                built.append((decl.order, len(built) + 10_000, empty))
                counts[decl.name] = 1
                continue
            problems.append(f"required element {decl.name} missing")
        for _, _, sub in sorted(built, key=lambda t: (t[0], t[1])):
            el.append(sub)
        return el, list(dict.fromkeys(problems))

    def _empty_element(self, decl: ElementDecl) -> etree._Element | None:
        """An element that is valid without content (all children optional), or None."""
        if decl.type_key is None:
            return None
        ct = self.model.complex[decl.type_key]
        if ct.simple_content is not None or any(a.required for a in ct.attributes.values()):
            return None
        if any(d.min_occurs >= 1 for d in ct.children):
            return None
        return etree.Element(decl.name)

    def _leaf(self, node: Node, simple: SimpleType | None, path: str) -> tuple[etree._Element, list[str]]:
        el = etree.Element(node.name)
        simple = simple or SimpleType("string")
        if node.children:
            return el, ["simple element cannot have children"]
        if node.text is None:
            if simple.base == "string" and not simple.min_length and not simple.enums:
                return el, []  # empty marker element (e.g. <Fee/>)
            return el, ["value missing"]
        try:
            el.text = normalize(node.text, simple)
        except ValueError as exc:
            el.text = node.text
            return el, [str(exc)]
        return el, []

    def _drop(self, path: str, value: str, reason: str, origin: str | None) -> None:
        self.dropped.append(Dropped(path, value, reason, (origin,) if origin else ()))

    def _drop_subtree(self, node: Node, path: str, reason: str) -> None:
        origins = node.origins()
        if origins or node.text:
            self.dropped.append(Dropped(path, node.text or "", reason, origins))


@dataclass
class SerializeResult:
    element: etree._Element | None
    dropped: list[Dropped]
    invalid: list[Dropped]


def serialize_at(model: SchemaModel, node: Node, path: list[str]) -> SerializeResult:
    """Serialise ``node`` as the element at ``path`` (element names below the root; [] = root)."""
    ser = Serializer(model)
    decl = model.decl_at(path)
    if decl is None:
        raise ValueError(f"unknown schema path {'/'.join(path)}")
    el, _bad = ser.element(node, decl, "/".join([model.root_element, *path]), required=True)
    return SerializeResult(el, ser.dropped, ser.invalid)
