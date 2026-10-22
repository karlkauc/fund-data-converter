"""Round trips through all three formats over folders of TPT and FundsXML files.

Every step goes through ``app.service.convert`` with an explicit direction, like the web app: the
intermediate files are real bytes (XLSX for TPT and openfunds) and are kept below ``<out>/<name>/``.

* TPT source: ``tpt→openfunds→fundsxml→tpt`` and ``tpt→fundsxml→openfunds→tpt``, compared field by field
  (as in ``batch_tpt_roundtrip.py``), plus the reference ``tpt→fundsxml→tpt``.
* FundsXML source: ``fundsxml→tpt→openfunds→fundsxml`` and ``fundsxml→openfunds→tpt→fundsxml``,
  compared leaf by leaf (path with keys instead of indexes → value; ControlData left out), plus the
  reference ``fundsxml→tpt→fundsxml``. TPT cannot hold everything a FundsXML file has, so what the
  three-format trip loses *beyond* the reference is reported separately.

Progress: every finished file is appended to ``<out>/files.jsonl``; ``report.json`` and ``summary.html``
are rewritten every ``--snapshot-every`` files and at the end. A new run continues where the last one
stopped (files already in ``files.jsonl`` are skipped) unless ``--fresh`` is given. TPT and FundsXML
files are interleaved so that early snapshots cover both.

Usage: python tools/batch_triangle_roundtrip.py [inputs ...] [--out DIR] [--only PATTERN] [--workers N]
       [--snapshot-every N] [--fresh] [--keep]
"""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
import time
import traceback
import zipfile
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from decimal import Decimal
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tools"))

from app.ingest.fundsxml_reader import parse_fundsxml  # noqa: E402
from app.ingest.tpt_reader import read_tpt  # noqa: E402
from app.model.xmltree import parse_date, parse_decimal  # noqa: E402
from app.service import Request, convert  # noqa: E402
from batch_tpt_roundtrip import _compare  # noqa: E402
from lxml import etree  # noqa: E402

CYCLES = {
    "tpt": {
        "tpt>of>fx>tpt": ["openfunds", "fundsxml", "tpt"],
        "tpt>fx>of>tpt": ["fundsxml", "openfunds", "tpt"],
        "ref:tpt>fx>tpt": ["fundsxml", "tpt"],
    },
    "fundsxml": {
        "fx>tpt>of>fx": ["tpt", "openfunds", "fundsxml"],
        "fx>of>tpt>fx": ["openfunds", "tpt", "fundsxml"],
        "ref:fx>tpt>fx": ["tpt", "fundsxml"],
    },
}
SHORT = {"tpt": "tpt", "fundsxml": "fx", "openfunds": "of"}
# Children whose text identifies one of several equal siblings, tried in this order.
KEYS = (
    "UniqueID",
    "Identifiers/ISIN",
    "Identifiers/LEI",
    "ISIN",
    "Identifiers/OtherID",
    "CountryCode",
    "NavDate",
    "Name",
)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "inputs",
        nargs="*",
        default=[str(ROOT / "testfiles" / "tpt"), str(ROOT / "testfiles" / "fundsxml")],
    )
    ap.add_argument("--out", default=str(ROOT / "testfiles" / "triangle_roundtrip"))
    ap.add_argument("--only", default="", help="substring filter on the path")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--keep", action="store_true", help="keep the intermediate files")
    ap.add_argument(
        "--snapshot-every",
        type=int,
        default=20,
        help="rewrite report.json every N files",
    )
    ap.add_argument("--fresh", action="store_true", help="ignore the progress of an earlier run")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    files = []
    for inp in map(Path, args.inputs):
        cands = [inp] if inp.is_file() else sorted(inp.rglob("*"))
        files += [
            p
            for p in cands
            if p.is_file()
            and p.suffix.lower() in (".xlsx", ".csv", ".xml")
            and ".DAV" not in p.parts
            and args.only in str(p)
            and _is_source(p)
        ]
    files = _interleave(files)
    progress = out / "files.jsonl"
    report: dict[str, dict] = {} if args.fresh else _load_progress(progress)
    if args.fresh:
        progress.unlink(missing_ok=True)
    todo = [p for p in files if _rel(p) not in report]
    total = len(report) + len(todo)
    print(f"{len(report)} done earlier, {len(todo)} to go", file=sys.stderr, flush=True)
    started = time.time()
    earlier = len(report)
    # A report right away: the first snapshot would otherwise wait for --snapshot-every files.
    _write_report(out, report, total, started, earlier)
    with (
        ProcessPoolExecutor(max_workers=args.workers) as pool,
        progress.open("a") as log,
    ):
        tasks = [pool.submit(_check_file, p, out, args.keep) for p in todo]
        for n, task in enumerate(as_completed(tasks), 1):
            rel, entry = task.result()
            report[rel] = entry
            log.write(json.dumps({"file": rel, **entry}, ensure_ascii=False, default=str) + "\n")
            log.flush()
            print(
                f"[{len(report)}/{total}] {rel}  {time.time() - started:.0f}s",
                file=sys.stderr,
                flush=True,
            )
            if n % args.snapshot_every == 0:
                _write_report(out, report, total, started, earlier)
    summary = _write_report(out, report, total, started, earlier)
    print(json.dumps(summary, indent=1, ensure_ascii=False, default=str))


def _is_source(path: Path) -> bool:
    """TPT files, and FundsXML documents only: no replies or other XML."""
    if path.suffix.lower() != ".xml":
        return True
    if path.name.upper().endswith("_REPLY.XML"):
        return False
    with path.open("rb") as f:
        return b"<FundsXML4" in f.read(4096)


def _rel(path: Path) -> str:
    return str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)


def _interleave(files: list[Path]) -> list[Path]:
    """TPT and FundsXML files alternating, each group in its own order."""
    xml = [p for p in files if p.suffix.lower() == ".xml"]
    tpt = [p for p in files if p.suffix.lower() != ".xml"]
    out: list[Path] = []
    step = max(1, round(len(tpt) / len(xml))) if xml else 1
    while xml or tpt:
        out += tpt[:step]
        tpt = tpt[step:]
        if xml:
            out.append(xml.pop(0))
    return out


def _load_progress(path: Path) -> dict[str, dict]:
    report: dict[str, dict] = {}
    if not path.exists():
        return report
    for line in path.read_text().splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue  # a line cut off by an abort
        report[entry.pop("file")] = entry
    return report


def _write_report(out: Path, report: dict[str, dict], total: int, started: float, earlier: int = 0) -> dict:
    """``earlier``: files done by a previous run; the remaining time is estimated from this run only."""
    report = dict(sorted(report.items()))
    summary = {
        "progress": f"{len(report)}/{total}",
        "elapsedSeconds": round(time.time() - started),
        "doneThisRun": len(report) - earlier,
    }
    summary |= _summary(report)
    body = json.dumps({"summary": summary, "files": report}, indent=1, ensure_ascii=False, default=str)
    # Write next to the target and rename, so a reader never sees half a report.
    for name, text in (("report.json", body), ("summary.html", _html(summary, report))):
        tmp = out / f".{name}.tmp"
        tmp.write_text(text)
        tmp.replace(out / name)
    return summary


def _step(data: bytes, filename: str, source: str, target: str) -> tuple[bytes, str, dict]:
    report, res = convert(Request(data, filename, direction=f"{source}-to-{target}", preview=False))
    body, name = res.data, res.filename
    if res.zipped:
        with zipfile.ZipFile(io.BytesIO(body)) as z:
            name = z.namelist()[0]
            body = z.read(name)
    info = {
        "issueCounts": report.get("issueCounts"),
        "issueCodes": dict(Counter(f"{i['level']}:{i['code']}" for i in report["issues"])),
        "dataLoss": report.get("dataLoss"),
    }
    return body, name, info


def _check_file(path: Path, out: Path, keep: bool) -> tuple[str, dict]:
    rel = str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)
    kind = "fundsxml" if path.suffix.lower() == ".xml" else "tpt"
    data = path.read_bytes()
    entry: dict = {"kind": kind, "cycles": {}}
    work = out / re.sub(r"[^\w.-]+", "_", rel.rsplit(".", 1)[0])
    try:
        if kind == "tpt":
            doc = read_tpt(data, path.name)
            entry.update(version=doc.version, rows=len(doc.rows))
            src_leaves = None
            entry["nav"] = _nav_tpt([r.values for r in doc.rows])
        else:
            src_owners: dict = {}
            src_root = parse_fundsxml(data)
            src_leaves = _leaves(src_root, src_owners)
            entry["nav"] = _nav_fundsxml(src_root)
            entry["leaves"] = len(src_leaves)
            entry["leavesByScope"] = dict(Counter(_scope(x, src_owners) for x in src_leaves))
    except Exception as exc:  # noqa: BLE001 – report and carry on
        entry["error"] = f"read: {type(exc).__name__}: {exc}"
        return rel, entry
    for name, chain in CYCLES[kind].items():
        cyc: dict = {"steps": []}
        entry["cycles"][name] = cyc
        cur, fname, src = data, path.name, kind
        try:
            for target in chain:
                label = f"{SHORT[src]}>{SHORT[target]}"
                cur, fname, info = _step(cur, fname, src, target)
                cyc["steps"].append({"step": label, **info})
                if keep:
                    work.mkdir(parents=True, exist_ok=True)
                    (
                        work / f"{name.replace(':', '_').replace('>', '-')}__{len(cyc['steps'])}_{fname}"
                    ).write_bytes(cur)
                src = target
            if kind == "tpt":
                back = read_tpt(cur, fname)
                cyc["nav"] = _nav_tpt([r.values for r in back.rows])
                diffs, added = _compare(doc, [r.values for r in back.rows])
                cyc.update(
                    rowsBack=len(back.rows),
                    diffs=len(diffs),
                    diffFields=dict(Counter(d[1] for d in diffs).most_common()),
                    diffSample=diffs[:10],
                    added=dict(added.most_common()),
                    _diffset=sorted({f"{d[0]}|{d[1]}" for d in diffs}),
                )
            else:
                back_root = parse_fundsxml(cur)
                cyc["nav"] = _nav_fundsxml(back_root)
                back = _leaves(back_root)
                lost, extra = src_leaves - back, back - src_leaves
                back_paths = dict(back)
                lost_paths = {p for p, _ in lost}
                changed = {(p, v) for p, v in lost if p in back_paths}
                cyc.update(
                    leavesBack=len(back),
                    lost=len(lost),
                    missing=len(lost - changed),
                    changed=len(changed),
                    added=len(extra - {(p, back_paths[p]) for p, _ in changed}),
                    lostByScope=dict(Counter(_scope(x, src_owners) for x in lost).most_common()),
                    missingPatterns=dict(
                        Counter(_where(x, src_owners) for x in lost - changed).most_common()
                    ),
                    changedPatterns=dict(Counter(_where(x, src_owners) for x in changed).most_common()),
                    addedPatterns=dict(
                        Counter(_pattern(p) for p, _ in extra if p not in lost_paths).most_common()
                    ),
                    missingSample=[f"{p} = {v}" for p, v in sorted(lost - changed)[:15]],
                    changedSample=[f"{p}: {v} → {back_paths[p]}" for p, v in sorted(changed)[:15]],
                    _lost=lost,
                    _owners=src_owners,
                )
        except Exception as exc:  # noqa: BLE001
            cyc["error"] = f"{type(exc).__name__}: {exc}"
            cyc["trace"] = traceback.format_exc(limit=6)
    _beyond_reference(entry)
    return rel, entry


def _beyond_reference(entry: dict) -> None:
    """What each three-format trip loses on top of the direct trip through TPT."""
    cycles = entry["cycles"]
    ref = next((c for n, c in cycles.items() if n.startswith("ref:")), {})
    for name, cyc in cycles.items():
        if name.startswith("ref:") or "error" in cyc or "error" in ref:
            continue
        if entry["kind"] == "tpt":
            extra = sorted(set(cyc["_diffset"]) - set(ref["_diffset"]))
            cyc["beyondRef"] = len(extra)
            cyc["beyondRefFields"] = dict(Counter(x.split("|", 1)[1] for x in extra).most_common())
            cyc["beyondRefSample"] = [d for d in cyc["diffSample"] if f"{d[0]}|{d[1]}" in set(extra)][:10]
        else:
            extra = cyc["_lost"] - ref["_lost"]
            cyc["beyondRef"] = len(extra)
            cyc["beyondRefPatterns"] = dict(Counter(_where(x, cyc["_owners"]) for x in extra).most_common())
            cyc["beyondRefSample"] = [f"{p} = {v}" for p, v in sorted(extra)[:15]]
    for cyc in cycles.values():
        cyc.pop("_diffset", None)
        cyc.pop("_lost", None)
        cyc.pop("_owners", None)


# -- FundsXML leaves -----------------------------------------------------------------


def _local(el) -> str:
    return etree.QName(el).localname


def _key(el) -> str:
    for k in KEYS:
        hit = el.find(k)
        if hit is not None and (hit.text or "").strip():
            return f"{k.rsplit('/', 1)[-1]}={hit.text.strip()}"
    return ""


def _position_key(pos, asset) -> str:
    """The instrument the position holds: its ISIN or other id, else the asset name; never UniqueID."""
    for el in (pos, asset):
        if el is None:
            continue
        for k in (
            "Identifiers/ISIN",
            "Identifiers/OtherID",
            "Identifiers/SEDOL",
            "Identifiers/CUSIP",
        ):
            text = (el.findtext(k) or "").strip()
            if text:
                return text
    return (asset.findtext("Name") if asset is not None else "") or "?"


def _leaves(root, owners: dict | None = None) -> set:
    """(path, value) of every element and attribute with text.

    Equal siblings are keyed, not indexed; a position carries its asset (``Position[<id>]/Asset/…``)
    and UniqueIDs (internal references) are left out.

    TPT has no fund level: a fund with five share classes comes back as five funds with one share
    class each, each with its own copy of the portfolio. So

    * portfolios are compared whoever holds them (``Portfolio[<NavDate>]/Positions/…``, a value held
      by several share classes counts once);
    * share class data as ``ShareClass[ISIN=…]/…``, whichever fund holds the share class;
    * fund data as one ``Funds/Fund/…``.

    ``owners`` collects, for portfolio values, whether the fund (``FundDynamicData``) or a share
    class holds them: a value only the fund-level portfolio has (a fund total next to the share
    classes' parts) belongs to the fund level when it is lost.
    """
    out: set = set()
    assets = {(a.findtext("UniqueID") or "").strip(): a for a in root.iterfind("AssetMasterData/Asset")}

    def add(item: tuple[str, str], owner: str) -> None:
        out.add(item)
        if owners is not None and item[0].startswith("Portfolio["):
            owners.setdefault(item, set()).add(owner)

    def walk(el, path: str, owner: str) -> None:
        children = [c for c in el if isinstance(c.tag, str)]
        tags = Counter(_local(c) for c in children)
        seen: Counter = Counter()
        positions: Counter = Counter()
        for c in children:
            tag = _local(c)
            if path == "" and tag in ("ControlData", "AssetMasterData"):
                continue
            if tag == "UniqueID" and _local(el) in ("Position", "Asset"):
                continue
            if tag == "Portfolios":
                level = "fund" if _local(el) == "FundDynamicData" else "shareclass"
                if owners is not None and level == "shareclass":
                    owners["#shareclass-portfolios"] = True
                walk(c, "", level)
                continue
            if tag == "Position":
                asset = assets.get((c.findtext("UniqueID") or "").strip())
                key = _position_key(c, asset)
                positions[key] += 1
                if positions[key] > 1:
                    key = f"{key}#{positions[key]}"
                p = f"{path}/Position[{key}]"
                walk(c, p, owner)
                if asset is not None:
                    walk(asset, p + "/Asset", owner)
                continue
            if tag == "ShareClass" and _local(el) == "ShareClasses":
                walk(c, f"ShareClass[{_key(c) or '?'}]", owner)
                continue
            step = tag
            if tag == "Fund" and _local(el) == "Funds":
                step = "Fund"
            elif tag == "Portfolio":
                step = f"Portfolio[{(c.findtext('NavDate') or '').strip()}]"
            elif c.get("ccy"):
                # Always by currency: one source amount may come back next to a second one.
                step = f"{tag}[{c.get('ccy')}]"
            elif tags[tag] > 1:
                if tag == "Attribute":
                    step = f"Attribute[{c.findtext('Name')}]"
                else:
                    key = _key(c)
                    seen[tag] += 1
                    step = f"{tag}[{key or seen[tag]}]"
            p = f"{path}/{step}" if path else step
            for a, v in c.attrib.items():
                add((f"{p}/@{etree.QName(a).localname}", _norm(v)), owner)
            text = (c.text or "").strip()
            if text and len(c) == 0:
                add((p, _norm(text)), owner)
            walk(c, p, owner)

    walk(root, "", "")
    return out


def _norm(v: str) -> str:
    v = v.strip()
    if re.fullmatch(r"-?\d+(\.\d+)?([eE][-+]?\d+)?", v):
        try:
            d = parse_decimal(v)
            return format(d.normalize(), "f") if d == d.to_integral() else str(d.normalize())
        except (ValueError, ArithmeticError):
            return v
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}([T ].*)?", v):
        try:
            return parse_date(v).isoformat() + (v[10:] if "T" in v and not v.endswith("T00:00:00") else "")
        except ValueError:
            return v
    return v


def _pattern(path: str) -> str:
    return re.sub(r"\[(?!TPT_|OF_)[^\]]*\]", "", path)


SCOPES = {
    "Funds": "Fondsebene",
    "ShareClass": "Anteilsklassen",
    "Portfolio": "Positionen",
    "RegulatoryReportings": "Regulatorische Blöcke",
}


def _fund_only(item: tuple[str, str], owners: dict) -> bool:
    """A value only the fund-level portfolio has, in a file whose share classes have portfolios too
    (otherwise the fund portfolio is the only one, and TPT repeats it for every share class)."""
    return bool(owners.get("#shareclass-portfolios")) and owners.get(item) == {"fund"}


def _where(item: tuple[str, str], owners: dict) -> str:
    """The path pattern for reports; a value only the fund-level portfolio holds as ``Funds/Fund/…``."""
    pattern = _pattern(item[0])
    if pattern.startswith("Portfolio/") and _fund_only(item, owners):
        return "Funds/Fund/" + pattern
    return pattern


def _scope(item: tuple[str, str], owners: dict) -> str:
    """Where a source value belongs; portfolio values only the fund-level portfolio has: fund level."""
    first = item[0].split("/", 1)[0].split("[", 1)[0]
    if first == "Portfolio" and _fund_only(item, owners):
        return "Fondsebene"
    return SCOPES.get(first, "Sonstiges")


# -- sum of the positions = net assets ---------------------------------------------

# Relative deviation still counted as equal (rounding of the positions' amounts).
NAV_TOLERANCE = Decimal("0.005")


def _dec(text: str | None) -> Decimal | None:
    try:
        return parse_decimal(text) if text and text.strip() else None
    except (ValueError, ArithmeticError):
        return None


def _close(a: Decimal, b: Decimal | None) -> bool:
    return b is not None and b != 0 and abs(a - b) <= abs(b) * NAV_TOLERANCE


def _verdict(total: Decimal, own: Decimal | None, fund: Decimal | None, weights: Decimal | None) -> str:
    """ok: the positions add up to the holder's net assets; fund: to the whole fund's (a fund
    portfolio repeated for a share class); differs; no_nav: nothing to compare with."""
    if _close(total, own):
        return "ok"
    if _close(total, fund) or (weights is not None and abs(weights - 1) <= NAV_TOLERANCE and own):
        return "fund"
    if own is None and fund is None:
        return "no_nav"
    return "differs"


def _pct_dev(total: Decimal, ref: Decimal | None) -> float | None:
    return float((total - ref) / ref * 100) if ref else None


def _navs(holder) -> dict[tuple[str, str], Decimal]:
    """(NavDate, currency) -> net assets of a fund (FundDynamicData) or share class."""
    out = {}
    if holder is None:
        return out
    for tav in holder.iterfind("TotalAssetValues/TotalAssetValue"):
        when = (tav.findtext("NavDate") or "").strip()
        for amount in tav.iterfind("TotalNetAssetValue/Amount"):
            value = _dec(amount.text)
            if value is not None:
                out.setdefault((when, amount.get("ccy", "")), value)
    return out


def _nav_fundsxml(root) -> list[dict]:
    """Per portfolio: the positions' TotalValue in the fund currency against the net assets."""
    out = []
    for fund in root.iterfind("Funds/Fund"):
        ccy = (fund.findtext("Currency") or "").strip()
        dyn = fund.find("FundDynamicData")
        fund_navs = _navs(dyn)
        holders = [("fund", fund.findtext("Names/OfficialName") or "?", dyn, fund_navs)]
        for sc in fund.iterfind("SingleFund/ShareClasses/ShareClass"):
            ident = sc.findtext("Identifiers/ISIN") or sc.findtext("Identifiers/OtherID") or "?"
            holders.append(("shareclass", ident, sc, _navs(sc)))
        for level, ident, holder, navs in holders:
            if holder is None:
                continue
            for pf in holder.iterfind("Portfolios/Portfolio"):
                when = (pf.findtext("NavDate") or "").strip()
                total, n, missing = Decimal(0), 0, 0
                percent = Decimal(0)
                for pos in pf.iterfind("Positions/Position"):
                    n += 1
                    percent += _dec(pos.findtext("TotalPercentage")) or 0
                    amounts = pos.findall("TotalValue/Amount")
                    amount = next((a for a in amounts if a.get("ccy") == ccy), None)
                    value = _dec(amount.text) if amount is not None else None
                    if value is None:
                        missing += 1
                    else:
                        total += value
                own = navs.get((when, ccy)) or next((v for (d, c), v in navs.items() if c == ccy), None)
                whole = fund_navs.get((when, ccy)) if level == "shareclass" else None
                out.append(
                    {
                        "level": level,
                        "id": ident,
                        "date": when,
                        "ccy": ccy,
                        "positions": n,
                        "withoutAmount": missing,
                        "sum": str(total.quantize(Decimal("0.01"))),
                        "nav": None if own is None else str(own),
                        "deviationPct": _pct_dev(total, own),
                        "weightsPct": str(percent.quantize(Decimal("0.0001"))),
                        # TotalPercentage is in percent; TPT 26 a fraction.
                        "result": _verdict(total, own, whole, percent / 100),
                    }
                )
    return out


def _nav_tpt(rows: list[dict[str, str]]) -> list[dict]:
    """Per TPT portfolio (fields 1 and 6): the sum of 24 against the net assets in 5."""
    groups: dict[tuple[str, str], list[dict[str, str]]] = {}
    for row in rows:
        groups.setdefault((row.get("1", ""), row.get("6", "")), []).append(row)
    out = []
    for (ident, when), members in groups.items():
        total = sum((v for r in members if (v := _dec(r.get("24"))) is not None), Decimal(0))
        weights = sum((v for r in members if (v := _dec(r.get("26"))) is not None), Decimal(0))
        nav = next((v for r in members if (v := _dec(r.get("5"))) is not None), None)
        out.append(
            {
                "level": "shareclass",
                "id": ident,
                "date": when,
                "ccy": members[0].get("4", ""),
                "positions": len(members),
                "withoutAmount": sum(1 for r in members if _dec(r.get("24")) is None),
                "sum": str(total.quantize(Decimal("0.01"))),
                "nav": None if nav is None else str(nav),
                "weights": str(weights),
                "deviationPct": _pct_dev(total, nav),
                "result": _verdict(total, nav, None, weights),
            }
        )
    return out


def _nav_counts(checks: list[dict]) -> Counter:
    return Counter(c["result"] for c in checks)


def _nav_summary(entries: dict[str, dict], cycles) -> dict:
    """Source portfolios per verdict, the deviating ones, and per trip the portfolios whose verdict
    got worse: a conversion that breaks the sum (more ``differs`` than in the source)."""
    source: Counter = Counter()
    deviating = []
    for rel, e in entries.items():
        for c in e.get("nav", []):
            source[c["result"]] += 1
            if c["result"] == "differs":
                deviating.append({"file": rel, **c})
    deviating.sort(key=lambda c: -abs(c["deviationPct"] or 0))
    trips = {}
    for name in cycles:
        back: Counter = Counter()
        worse = []
        for rel, e in entries.items():
            cyc = e["cycles"].get(name, {})
            if "nav" not in cyc:
                continue
            got = _nav_counts(cyc["nav"])
            back.update(got)
            if got["differs"] > _nav_counts(e.get("nav", []))["differs"]:
                worse.append(rel)
        trips[name] = {
            "results": dict(back),
            "worseFiles": len(worse),
            "worseSample": worse[:15],
        }
    return {
        "source": dict(source),
        "deviating": len(deviating),
        "deviatingSample": deviating[:25],
        "trips": trips,
    }


# -- report ------------------------------------------------------------------------


def _summary(report: dict[str, dict]) -> dict:
    out: dict = {
        "files": len(report),
        "kinds": dict(Counter(e["kind"] for e in report.values())),
        "readErrors": {k: e["error"] for k, e in report.items() if "error" in e},
    }
    out["nav"] = {}
    for kind, cycles in CYCLES.items():
        entries = {k: e for k, e in report.items() if e["kind"] == kind and "error" not in e}
        out["nav"][kind] = _nav_summary(entries, cycles)
        for name in cycles:
            cs = {k: e["cycles"][name] for k, e in entries.items() if name in e["cycles"]}
            ok = {k: c for k, c in cs.items() if "error" not in c}
            s: dict = {
                "files": len(cs),
                "errors": dict(
                    Counter(c["error"][:160] for c in cs.values() if "error" in c).most_common(15)
                ),
                "errorFiles": [k for k, c in cs.items() if "error" in c][:20],
            }
            if kind == "tpt":
                fields, beyond = Counter(), Counter()
                for c in ok.values():
                    fields.update(c["diffFields"])
                    beyond.update(c.get("beyondRefFields", {}))
                s.update(
                    lossless=sum(1 for c in ok.values() if not c["diffs"]),
                    diffs=sum(c["diffs"] for c in ok.values()),
                    diffFields=dict(fields.most_common(30)),
                )
            else:
                patterns, changed, beyond = Counter(), Counter(), Counter()
                scope_lost, scope_src = Counter(), Counter()
                for k, c in ok.items():
                    scope_lost.update(c.get("lostByScope", {}))
                    scope_src.update(entries[k].get("leavesByScope", {}))
                    patterns.update(c["missingPatterns"])
                    changed.update(c["changedPatterns"])
                    beyond.update(c.get("beyondRefPatterns", {}))
                s.update(
                    lossless=sum(1 for c in ok.values() if not c["lost"]),
                    lostLeaves=sum(c["lost"] for c in ok.values()),
                    sourceLeaves=sum(entries[k]["leaves"] for k in ok),
                    missing=sum(c["missing"] for c in ok.values()),
                    changed=sum(c["changed"] for c in ok.values()),
                    missingPatterns=dict(patterns.most_common(40)),
                    changedPatterns=dict(changed.most_common(40)),
                    byScope={
                        scope: {"source": scope_src[scope], "lost": scope_lost[scope]}
                        for scope in sorted(
                            set(scope_src) | set(scope_lost),
                            key=lambda x: -scope_src[x],
                        )
                    },
                )
            if not name.startswith("ref:"):
                s.update(
                    noLossBeyondRef=sum(1 for c in ok.values() if not c.get("beyondRef")),
                    beyondRef=sum(c.get("beyondRef", 0) for c in ok.values()),
                    beyondRefTop=dict(beyond.most_common(40)),
                    beyondRefFiles=[k for k, c in ok.items() if c.get("beyondRef")][:20],
                )
            out[name] = s
    return out


CYCLE_LABEL = {
    "tpt>of>fx>tpt": "TPT → openfunds → FundsXML → TPT",
    "tpt>fx>of>tpt": "TPT → FundsXML → openfunds → TPT",
    "ref:tpt>fx>tpt": "Referenz: TPT → FundsXML → TPT",
    "fx>tpt>of>fx": "FundsXML → TPT → openfunds → FundsXML",
    "fx>of>tpt>fx": "FundsXML → openfunds → TPT → FundsXML",
    "ref:fx>tpt>fx": "Referenz: FundsXML → TPT → FundsXML",
}

CSS = """
:root { --bg:#f8fafc; --panel:#fff; --text:#0f172a; --muted:#64748b; --line:#e2e8f0;
  --ok:#047857; --warn:#b45309; --bad:#b91c1c; --bar:#3b82f6; --bar2:#f59e0b; }
@media (prefers-color-scheme: dark) { :root { --bg:#0b1220; --panel:#111a2e; --text:#e2e8f0;
  --muted:#94a3b8; --line:#1e293b; --ok:#34d399; --warn:#fbbf24; --bad:#f87171; } }
* { box-sizing:border-box; }
body { margin:0; padding:24px 16px 48px; background:var(--bg); color:var(--text);
  font:14px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width:1100px; margin:0 auto; }
h1 { font-size:22px; margin:0 0 4px; } h2 { font-size:17px; margin:32px 0 8px; }
h3 { font-size:14px; margin:16px 0 6px; color:var(--muted); font-weight:600; }
.muted { color:var(--muted); } .ok { color:var(--ok); }
.warn { color:var(--warn); } .bad { color:var(--bad); }
.panel { background:var(--panel); border:1px solid var(--line); border-radius:10px;
  padding:16px; margin:12px 0; }
.progress { height:10px; background:var(--line); border-radius:99px; overflow:hidden; margin:10px 0 4px; }
.progress > div { height:100%; background:var(--bar); }
table { width:100%; border-collapse:collapse; }
th, td { text-align:left; padding:6px 8px; border-bottom:1px solid var(--line); vertical-align:top; }
th { font-size:12px; text-transform:uppercase; letter-spacing:.03em; color:var(--muted); font-weight:600; }
td.num, th.num { text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap; }
code { font:12px/1.4 ui-monospace, SFMono-Regular, Menlo, monospace; word-break:break-all; }
.bar { display:inline-block; height:8px; border-radius:4px; background:var(--bar2); vertical-align:middle; }
.wrap { overflow-x:auto; }
details summary { cursor:pointer; color:var(--muted); margin:8px 0; }
"""


def _n(value: int) -> str:
    """German thousands separator: 62.977."""
    return f"{value:,}".replace(",", ".")


def _pct(n: int, total: int) -> str:
    return f"{100 * n / total:.1f} %".replace(".", ",") if total else "–"


def _patterns_table(title: str, patterns: dict, limit: int = 25) -> str:
    if not patterns:
        return ""
    rows = list(patterns.items())[:limit]
    top = max(v for _, v in rows) or 1
    body = "".join(
        f'<tr><td><code>{escape(k)}</code></td><td class="num">{_n(v)}</td>'
        f'<td style="width:140px"><span class="bar" '
        f'style="width:{max(2, round(120 * v / top))}px"></span></td></tr>'
        for k, v in rows
    )
    more = f'<p class="muted">… und {len(patterns) - limit} weitere</p>' if len(patterns) > limit else ""
    return (
        f'<h3>{escape(title)}</h3><div class="wrap"><table><tr><th>Pfad / Feld</th>'
        f'<th class="num">Anzahl</th><th></th></tr>{body}</table></div>{more}'
    )


NAV_LABEL = {
    "ok": "Summe = Volumen",
    "fund": "Summe = Fondsvolumen (Gesamtportfolio je Anteilsklasse)",
    "differs": "weicht ab",
    "no_nav": "kein Volumen angegeben",
}


def _dev(pct: float | None) -> str:
    return "" if pct is None else f"{pct:+.2f} %".replace(".", ",")


def _nav_html(nav: dict) -> str:
    if not nav:
        return ""
    out = [
        (
            "<h2>Summe der Positionen = Volumen</h2><div class=panel>"
            '<p class="muted">Je Portfolio: Summe der Positionswerte in Portfoliowährung (FundsXML '
            "<code>TotalValue</code>, TPT Feld 24) gegen das Nettovermögen der Anteilsklasse "
            f"(FundsXML <code>TotalNetAssetValue</code>, TPT Feld 5); "
            f"Toleranz {_n(int(NAV_TOLERANCE * 1000))}‰."
            "</p>"
        )
    ]
    for kind, label in (("tpt", "TPT-Quellen"), ("fundsxml", "FundsXML-Quellen")):
        k = nav.get(kind)
        if not k or not k["source"]:
            continue
        total = sum(k["source"].values())
        cells = "".join(
            f"<tr><td>{escape(NAV_LABEL.get(r, r))}</td><td class=num>{_n(v)}</td>"
            f"<td class=num>{_pct(v, total)}</td></tr>"
            for r, v in sorted(k["source"].items(), key=lambda x: -x[1])
        )
        out.append(
            f"<h3>{label}: {_n(total)} Portfolios</h3><div class=wrap><table>"
            "<tr><th>Ergebnis</th><th class=num>Portfolios</th><th class=num>Anteil</th></tr>"
            f"{cells}</table></div>"
        )
        trips = "".join(
            f"<li>{escape(CYCLE_LABEL.get(n, n))}: "
            + (
                '<span class="ok">keine Verschlechterung</span>'
                if not t["worseFiles"]
                else f'<span class="bad">{t["worseFiles"]} Datei(en) mit neuen Abweichungen</span>'
            )
            + "</li>"
            for n, t in k["trips"].items()
        )
        out.append(f"<ul>{trips}</ul>")
        if k["deviatingSample"]:
            rows = "".join(
                f"<tr><td><code>{escape(d['file'].split('/')[-1])}</code></td><td>{escape(d['id'])}</td>"
                f"<td>{escape(d['date'])}</td><td class=num>{_n(d['positions'])}</td>"
                f"<td class=num>{escape(d['sum'])}</td><td class=num>{escape(d['nav'] or '–')}</td>"
                f"<td class=num>{_dev(d['deviationPct'])}</td></tr>"
                for d in k["deviatingSample"]
            )
            out.append(
                f"<details><summary>{_n(k['deviating'])} abweichende Portfolios (größte zuerst)</summary>"
                "<div class=wrap><table><tr><th>Datei</th><th>Portfolio</th><th>Stichtag</th>"
                "<th class=num>Positionen</th><th class=num>Summe</th><th class=num>Volumen</th>"
                f"<th class=num>Abw.</th></tr>{rows}</table></div></details>"
            )
    out.append("</div>")
    return "".join(out)


def _html(summary: dict, report: dict[str, dict]) -> str:
    done, total = (int(x) for x in summary["progress"].split("/"))
    elapsed = summary["elapsedSeconds"]
    eta = ""
    this_run = summary.get("doneThisRun", done)
    if this_run > 0 and done < total and elapsed:
        rest = elapsed / this_run * (total - done)
        eta = f" · noch etwa {rest / 3600:.1f} h" if rest >= 3600 else f" · noch etwa {rest / 60:.0f} min"
    kinds = ", ".join(f"{v} {'TPT' if k == 'tpt' else 'FundsXML'}" for k, v in summary["kinds"].items())
    out = [
        (
            f"<!doctype html><html lang=de><head><meta charset=utf-8>"
            f'<meta name=viewport content="width=device-width,initial-scale=1">'
            f"<title>Dreiformat-Ringtausch</title><style>{CSS}</style></head><body><main>"
        ),
        "<h1>Dreiformat-Ringtausch</h1>",
        (
            f'<p class="muted">Stand {time.strftime("%d.%m.%Y %H:%M")} · {done} von {total} Dateien '
            f"({kinds}) · läuft seit {elapsed / 60:.0f} min{eta}</p>"
        ),
        f'<div class="progress"><div style="width:{100 * done / total if total else 0:.1f}%"></div></div>',
    ]
    if summary["readErrors"]:
        out.append(f'<p class="bad">{len(summary["readErrors"])} Datei(en) nicht lesbar</p>')

    # Overview: one row per cycle.
    rows = []
    for name, label in CYCLE_LABEL.items():
        c = summary.get(name)
        if not c or not c["files"]:
            continue
        ok = c["files"] - len(c["errorFiles"])
        beyond = (
            f'<td class="num {"ok" if not c["beyondRef"] else "warn"}">{c["noLossBeyondRef"]} / {ok}'
            f' <span class="muted">({_n(c["beyondRef"])} Werte)</span></td>'
            if "noLossBeyondRef" in c
            else '<td class="num muted">–</td>'
        )
        scopes = "".join(
            f"<br><span class=muted>{escape(name)}: {_n(v['lost'])} von {_n(v['source'])} "
            f"({_pct(v['lost'], v['source'])})</span>"
            for name, v in c.get("byScope", {}).items()
            if v["source"] or v["lost"]
        )
        detail = (
            f"{_n(c['diffs'])} Feldabweichungen"
            if "diffs" in c
            else f"{_n(c['missing'])} fehlen, {_n(c['changed'])} geändert von {_n(c['sourceLeaves'])} "
            f"({_pct(c['missing'] + c['changed'], c['sourceLeaves'])})"
        )
        rows.append(
            f"<tr><td>{escape(label)}</td><td class=num>{c['files']}</td>"
            f'<td class="num {"bad" if c["errorFiles"] else ""}">{len(c["errorFiles"])}</td>'
            f'<td class="num {"ok" if c["lossless"] == ok else ""}">{c["lossless"]} / {ok}</td>'
            f"{beyond}<td>{detail}{scopes}</td></tr>"
        )
    out.append(
        '<div class="panel wrap"><table><tr><th>Umlauf</th><th class=num>Dateien</th>'
        "<th class=num>Fehler</th><th class=num>verlustfrei</th>"
        "<th class=num>ohne Verlust über Referenz hinaus</th><th>Abweichungen</th></tr>"
        + "".join(rows)
        + "</table>"
        '<p class="muted">Referenz = direkter Weg über TPT. „Über Referenz hinaus“ ist, was der Weg über '
        "openfunds zusätzlich verliert. Bei FundsXML-Quellen fehlt vieles schon, "
        "weil TPT dafür kein Feld hat."
        "</p></div>"
    )

    out.append(_nav_html(summary.get("nav", {})))

    for name, label in CYCLE_LABEL.items():
        c = summary.get(name)
        if not c or not c["files"]:
            continue
        out.append(f"<h2>{escape(label)}</h2><div class=panel>")
        if c.get("beyondRefTop"):
            out.append(_patterns_table("Zusätzlich zur Referenz verloren", c["beyondRefTop"]))
            samples = []
            for rel in c.get("beyondRefFiles", [])[:10]:
                cyc = report.get(rel, {}).get("cycles", {}).get(name, {})
                items = "".join(
                    f"<li><code>{escape(str(x))}</code></li>" for x in cyc.get("beyondRefSample", [])[:5]
                )
                samples.append(
                    f"<li><code>{escape(rel)}</code> – {_n(cyc.get('beyondRef', 0))} Werte"
                    f"<ul>{items}</ul></li>"
                )
            if samples:
                out.append(f"<details><summary>Beispiele</summary><ul>{''.join(samples)}</ul></details>")
        if "diffFields" in c:
            out.append(_patterns_table("Abweichende TPT-Felder", c["diffFields"]))
        if "missingPatterns" in c:
            out.append(
                "<details><summary>Fehlende und geänderte Werte nach Pfad</summary>"
                + _patterns_table("Fehlen", c["missingPatterns"], 40)
                + _patterns_table("Geändert", c["changedPatterns"], 40)
                + "</details>"
            )
        if c["errors"]:
            errs = "".join(f"<li>{n}× {escape(e)}</li>" for e, n in c["errors"].items())
            files = "".join(f"<li><code>{escape(f)}</code></li>" for f in c["errorFiles"])
            out.append(
                f'<h3 class="bad">Fehler</h3><ul>{errs}</ul>'
                f"<details><summary>Dateien</summary><ul>{files}</ul></details>"
            )
        if not (c.get("beyondRefTop") or c.get("diffFields") or c.get("missingPatterns") or c["errors"]):
            out.append('<p class="ok">Keine Abweichungen.</p>')
        out.append("</div>")
    out.append("</main></body></html>")
    return "".join(out)


if __name__ == "__main__":
    main()
