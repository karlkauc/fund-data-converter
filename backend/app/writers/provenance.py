"""Where a converted file comes from, written into the file itself.

FundsXML gets an XML comment after the declaration; XLSX files get it as document properties
(File → Info in Excel): author, title, subject, description and creation time, plus one custom
property per item. CSV has no place for it: a comment line would break the files' readers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from app import release_version
from app.config import settings

APP_NAME = "Fund Data Converter"
NOTE = "Converted automatically from the source file; check it against the source before relying on it."


@dataclass(frozen=True)
class Provenance:
    source_file: str
    source_format: str  # "TPT V7", "openfunds", "FundsXML"
    target_format: str  # "FundsXML 4.2.11", "TPT V8", "openfunds 2.13.0"
    contents: str = ""  # "1 fund, 2 share classes, 120 positions"
    converted_at: datetime = field(default_factory=lambda: datetime.now(UTC).replace(microsecond=0))

    @property
    def conversion(self) -> str:
        return f"{self.source_format} → {self.target_format}"

    def items(self) -> list[tuple[str, str]]:
        """(label, value) in the order shown."""
        out = [
            ("Converted with", f"{APP_NAME} {release_version()} ({settings.site_origin})"),
            ("Converted at", self.converted_at.strftime("%Y-%m-%dT%H:%M:%SZ")),
            ("Source file", self.source_file),
            ("Conversion", self.conversion),
        ]
        if self.contents:
            out.append(("Contents", self.contents))
        out.append(("Note", NOTE))
        return out


def _comment_text(value: str) -> str:
    """Text an XML comment can hold: no "--", no trailing "-", one line."""
    text = " ".join(value.split())
    while "--" in text:
        text = text.replace("--", "- -")
    return text.rstrip("-")


def with_xml_comment(xml: bytes, prov: Provenance) -> bytes:
    """``xml`` with a comment naming its origin right after the XML declaration."""
    width = max(len(label) for label, _ in prov.items())
    lines = [f"  {label + ':':<{width + 1}} {_comment_text(value)}" for label, value in prov.items()]
    comment = ("<!--\n" + "\n".join(lines) + "\n-->\n").encode("utf-8")
    if xml.startswith(b"<?xml"):
        end = xml.index(b"?>") + 2
        rest = xml[end:].lstrip(b"\r\n")
        return xml[:end] + b"\n" + comment + rest
    return comment + xml


def apply_to_workbook(wb, prov: Provenance) -> None:
    """Document properties of an openpyxl workbook (also a write-only one), before it is saved."""
    from openpyxl.packaging.custom import StringProperty

    created = prov.converted_at.replace(tzinfo=None)  # openpyxl writes naive datetimes as UTC
    props = wb.properties
    props.creator = APP_NAME
    props.lastModifiedBy = APP_NAME
    props.title = f"{prov.target_format} from {prov.source_file}"[:255]
    props.subject = prov.conversion
    props.description = "\n".join(f"{label}: {value}" for label, value in prov.items())
    props.keywords = "TPT, FundsXML, openfunds, converted"
    props.created = props.modified = created
    for label, value in prov.items():
        wb.custom_doc_props.append(StringProperty(name=label, value=value[:255]))
