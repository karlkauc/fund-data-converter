"""Build backend/app/spec/openfunds.json from the official openfunds field list PDF.

openfunds publishes its fields only as a PDF ("Openfunds Fields (sorted by OF-ID)",
exported from MS Access). This script extracts the text with ``pdftotext -layout``
(poppler-utils) and parses one record per OF-ID. FinDatEx references in the
descriptions ("TPT: 26_Valuation_weight", "EMT: 00001_EMT_Version") are kept as
``findatex``, so the template fields can be joined with the FundsXML schema.
Multiple-country fields (``OFST6010XX``) are kept with ``country_pattern``; in a file
the ``XX`` is an ISO country code.

Usage: python tools/sync_openfunds.py [path/to/openfunds_fields.pdf | URL]
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "backend" / "app" / "spec" / "openfunds.json"
DEFAULT_URL = (
    "https://openfunds.org/wp-content/uploads/2026/03/openfunds_fields_v2.13.0.pdf"
)

_PAGE = re.compile(r"(?m)^\s*Printed \d\d\.\d\d\.\d{4} [\d:]+\s+Page \d+ of \d+\s*$")
_SECTION = re.compile(r"(?m)^\s*OF[A-Z]{2}[0-9X]{6} - OF[A-Z]{2}[0-9X]{6}\b.*$")
_HEAD = re.compile(r"OF-ID +(OF[A-Z]{2}\d{4}[0-9X]{2}) +Field Name +(.*)")
_REF = re.compile(r"\b(TPT|EMT|EPT|EET|EFT|DCPT):\s*(\d+[a-z]?)_([A-Za-z0-9_]+)")
_QUOTED = re.compile(r"[\"“”]([^\"“”]+)[\"“”]")


def pdf_text(source: str) -> tuple[str, str]:
    if re.match(r"https?://", source):
        req = urllib.request.Request(source, headers={"User-Agent": "Mozilla/5.0"})
        data = urllib.request.urlopen(req, timeout=120).read()
    else:
        data = Path(source).read_bytes()
    with tempfile.NamedTemporaryFile(suffix=".pdf") as tmp:
        tmp.write(data)
        tmp.flush()
        text = subprocess.run(
            ["pdftotext", "-layout", tmp.name, "-"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    return text, hashlib.sha256(data).hexdigest()


def _flow(lines: list[str]) -> str:
    """Join wrapped lines into paragraphs; blank lines separate paragraphs."""
    paras, cur = [], []
    for line in lines:
        s = line.strip()
        if s:
            cur.append(s)
        elif cur:
            paras.append(" ".join(cur))
            cur = []
    if cur:
        paras.append(" ".join(cur))
    return "\n\n".join(paras)


def _section(lines: list[str], start: str, stop: tuple[str, ...]) -> list[str]:
    """Lines from the label ``start`` (label stripped) up to the next ``stop`` label."""
    out: list[str] | None = None
    for line in lines:
        if out is not None and line.startswith(stop):
            break
        if out is None and line.startswith(start):
            out = [" " * len(start) + line[len(start) :]]
        elif out is not None:
            out.append(line)
    return out or []


def parse_block(block: str) -> dict:
    lines = block.splitlines()
    m = _HEAD.match(lines[0])
    of_id, name = m.group(1), m.group(2).strip()

    def label(lbl: str, rest: str = r"(.*?)") -> str:
        mm = re.search(rf"(?m)^{lbl} +{rest}(?: {{2,}}|$)", block)
        return mm.group(1).strip() if mm else ""

    intro = re.search(r"Introduced / Revoked +(\S+) +/ +(\S+)", block)
    link = re.search(r"Link Reference *(OF[A-Z]{2}\d{6})?", block)
    description = _flow(_section(lines, "Description", ("Values", "Example")))
    values = _flow(_section(lines, "Values", ("Example",)))
    example = _flow(_section(lines, "Example", ("\x00",)))
    flat = re.sub(r"\s+", " ", description)
    refs = []
    for tpl, num, rest in _REF.findall(flat):
        ref = {"template": tpl, "num": num, "name": f"{num}_{rest}"}
        if ref not in refs:
            refs.append(ref)
    return {
        "id": of_id,
        "name": name,
        "country_pattern": of_id.endswith("XX"),
        "tags": [t.strip() for t in label("Field Tags").split("|") if t.strip()],
        "level": label("Field Level").title().replace("Share class", "Share Class"),
        "type": label("Data Type", r"(\S+)").lower(),
        "link": link.group(1) if link and link.group(1) else "",
        "introduced": intro.group(1) if intro else "",
        "revoked": "" if not intro or intro.group(2) == "--" else intro.group(2),
        "description": description,
        "values": values,
        "codes": _QUOTED.findall(values)
        if values.lstrip().startswith(('"', "“"))
        else [],
        "example": example,
        "findatex": refs,
    }


def parse(text: str) -> tuple[dict, list[dict]]:
    text = _PAGE.sub("", text.replace("\f", "\n"))
    version = re.search(r"Version:\s+Version ([\d.]+)", text)
    date = re.search(r"Date:\s+(\d{4}-\d\d-\d\d)", text)
    body = _SECTION.sub("", text)
    blocks = re.split(r"(?m)^(?=OF-ID +OF[A-Z]{2}\d{4}[0-9X]{2})", body)[1:]
    meta = {
        "version": version.group(1) if version else "",
        "date": date.group(1) if date else "",
    }
    return meta, [parse_block(b) for b in blocks]


def main() -> None:
    source = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URL
    text, sha = pdf_text(source)
    meta, fields = parse(text)
    payload = {"source": Path(source).name, "sha256": sha, **meta, "fields": fields}
    TARGET.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", "utf-8")
    print(
        f"{TARGET.name}: openfunds {meta['version']} ({meta['date']}), {len(fields)} fields"
    )


if __name__ == "__main__":
    main()
