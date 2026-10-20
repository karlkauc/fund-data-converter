"""TPT → FundsXML → TPT over a folder of TPT files.

For every ``*.xlsx`` / ``*.csv`` below the input folder, with and without the
TPT block in the FundsXML:

* XSD validity of the generated FundsXML;
* structure: one ``Fund`` per TPT portfolio, its positions under
  ``SingleFund/ShareClasses/ShareClass`` whose ISIN is field 1, nothing under
  ``FundDynamicData/Portfolios``;
* losslessness: every value of the source comes back (numbers and dates by
  value); fields the source leaves empty and FundsXML implies are counted as
  additions, not differences.

The core-only round trip is written to ``<out>/<name>_roundtrip.xlsx`` and,
like the source, validated with findatex-validator; the report lists the rules
that fire on the round trip but not on the source.

Usage: python tools/batch_tpt_roundtrip.py [input] [--out DIR] [--validator URL]
       [--profiles SOLVENCY_II] [--no-validate] [--only PATTERN] [--jobs N] [--workers N]
       [--validate-list FILE] [--retry-failed]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tools"))

import httpx  # noqa: E402
from batch_tpt_check import _validate  # noqa: E402
from lxml import etree  # noqa: E402

from app.convert.derive import DERIVED_FIELDS  # noqa: E402
from app.convert.to_fundsxml import ConvertOptions, convert_tpt_to_fundsxml  # noqa: E402
from app.convert.to_tpt import extract_tpt  # noqa: E402
from app.ingest.fundsxml_reader import parse_fundsxml  # noqa: E402
from app.ingest.tpt_reader import read_tpt  # noqa: E402
from app.model.xmltree import parse_date, parse_decimal  # noqa: E402
from app.writers.tpt_writer import write_xlsx  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("input", nargs="?", default=str(ROOT / "testfiles" / "tpt"))
    ap.add_argument("--out", default=str(ROOT / "testfiles" / "tpt_roundtrip"))
    ap.add_argument("--validator", default="http://127.0.0.1:18082")
    ap.add_argument("--profiles", nargs="+", default=["SOLVENCY_II"])
    ap.add_argument("--no-validate", action="store_true")
    ap.add_argument("--only", default="", help="substring filter on the relative path")
    ap.add_argument("--jobs", type=int, default=4, help="parallel validator requests")
    ap.add_argument("--workers", type=int, default=4, help="parallel conversion processes")
    ap.add_argument("--validate-list", help="file with relative paths; only these are validated")
    ap.add_argument(
        "--retry-failed",
        action="store_true",
        help="only repeat the validations that failed in <out>/report.json (no new conversion)",
    )
    args = ap.parse_args()

    src, out = Path(args.input), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    if args.retry_failed:
        _retry_failed(args, src, out)
        return
    files = sorted(
        p
        for p in src.rglob("*")
        if p.suffix.lower() in (".xlsx", ".csv")
        and ".DAV" not in p.parts
        and args.only in str(p.relative_to(src))
    )
    pool = ThreadPoolExecutor(max_workers=args.jobs)
    client = httpx.Client(timeout=900)
    report: dict[str, dict] = {}
    pending = []
    started = time.time()
    with ProcessPoolExecutor(max_workers=args.workers) as workers:
        listed = set(Path(args.validate_list).read_text().split()) if args.validate_list else None

        def validate(path: Path) -> bool:
            return not args.no_validate and (listed is None or str(path.relative_to(src)) in listed)

        tasks = [workers.submit(_check_file, path, src, out, validate(path)) for path in files]
        for n, task in enumerate(as_completed(tasks), 1):
            rel, entry, target = task.result()
            report[rel] = entry
            if target is not None:
                val = entry["validation"] = {"source": {}, "roundtrip": {}}
                for file, res_v in ((src / rel, val["source"]), (target, val["roundtrip"])):
                    pending.append(pool.submit(_validate, client, args, file, entry["version"], res_v))
            print(f"[{n}/{len(files)}] {rel}  {time.time() - started:.0f}s", file=sys.stderr, flush=True)
    for f in pending:
        f.result()
    pool.shutdown()
    report = dict(sorted(report.items()))
    _unwrap(report)

    summary = _summary(report)
    (out / "report.json").write_text(
        json.dumps({"summary": summary, "files": report}, indent=1, ensure_ascii=False, default=str)
    )
    print(json.dumps(summary, indent=1, ensure_ascii=False, default=str))


def _unwrap(report: dict[str, dict]) -> None:
    """``_validate`` stores its result under ``validation`` of the dict it gets; lift it one level."""
    for entry in report.values():
        for side in entry.get("validation", {}).values():
            inner = side.pop("validation", None)
            if inner is not None:
                side.update(inner)


def _retry_failed(args, src: Path, out: Path) -> None:
    report = json.loads((out / "report.json").read_text())["files"]
    _unwrap(report)
    client = httpx.Client(timeout=900)
    jobs = []
    for rel, entry in report.items():
        val = entry.get("validation")
        if not val:
            continue
        for side, file in (("source", src / rel), ("roundtrip", out / entry.get("roundtripFile", ""))):
            if "errors" not in val[side]:
                val[side] = {}
                jobs.append((file, entry["version"], val[side]))
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        for f in [pool.submit(_validate, client, args, *job) for job in jobs]:
            f.result()
    _unwrap(report)
    print(f"{len(jobs)} validation(s) repeated", file=sys.stderr)
    summary = _summary(report)
    (out / "report.json").write_text(
        json.dumps({"summary": summary, "files": report}, indent=1, ensure_ascii=False, default=str)
    )
    print(json.dumps(summary, indent=1, ensure_ascii=False, default=str))


def _check_file(path: Path, src: Path, out: Path, keep: bool) -> tuple[str, dict, Path | None]:
    """Both round trips of one file; ``keep`` writes the core-only result for validation."""
    rel = str(path.relative_to(src))
    entry: dict = {}
    target = None
    try:
        doc = read_tpt(path.read_bytes(), path.name)
        entry.update(
            version=doc.version,
            rows=len(doc.rows),
            portfolios=len({(r.get("1"), r.get("6")) for r in doc.rows}),
            readerIssues=dict(Counter(f"{i.level}:{i.code}" for i in doc.issues)),
        )
        for mode, block in (("block", True), ("core", False)):
            res = convert_tpt_to_fundsxml(doc, ConvertOptions(include_block=block))
            back = extract_tpt(parse_fundsxml(res.xml), doc.version)
            diffs, added = _compare(doc, back.rows)
            entry[mode] = {
                "xsdValid": res.valid,
                "xsdErrors": res.validation_errors[:3],
                "converterIssues": dict(Counter(f"{i.level}:{i.code}" for i in res.issues)),
                "structure": _structure(res.xml, doc),
                "versionBack": back.version,
                "rowsBack": len(back.rows),
                "diffs": len(diffs),
                "diffFields": dict(Counter(d[1] for d in diffs).most_common(15)),
                "diffSample": diffs[:5],
                "added": dict(added.most_common()),
            }
            if mode == "core" and keep:
                target = out / (rel.replace("/", "__").rsplit(".", 1)[0] + "_roundtrip.xlsx")
                target.write_bytes(write_xlsx(back.rows, doc.version))
                entry["roundtripFile"] = target.name
    except Exception as exc:  # noqa: BLE001 – report and carry on with the next file
        entry["error"] = f"{type(exc).__name__}: {exc}"
        entry["trace"] = traceback.format_exc(limit=5)
        target = None
    return rel, entry, target


def _same(a: str, b: str) -> bool:
    if a == b:
        return True
    for parse in (parse_decimal, parse_date):
        try:
            if parse(a) == parse(b):
                return True
        except ValueError:
            continue
    return False


def _compare(doc, rows: list[dict[str, str]]) -> tuple[list[tuple], Counter]:
    """Differences (row, field, source, back) and the fields added where the source is empty."""
    if len(rows) != len(doc.rows):
        return [(None, "row count", len(doc.rows), len(rows))], Counter()
    diffs, added = [], Counter()
    for orig, back in zip(doc.rows, rows, strict=True):
        for key in set(orig.values) | set(back):
            a, b = orig.values.get(key, ""), back.get(key, "")
            if key == "1000" and doc.version == "V7":
                continue  # the label is normalised to the official one
            if not a and b and key in DERIVED_FIELDS:
                added[key] += 1
            elif not _same(a, b):
                diffs.append((orig.source_row, key, a, b))
    return diffs, added


def _structure(xml: bytes, doc) -> list[str]:
    root = etree.fromstring(xml)
    problems = []
    ids = {r.get("1") for r in doc.rows}
    funds = root.findall("Funds/Fund")
    if funds and len(funds) != len({(r.get("1"), r.get("6")) for r in doc.rows}):
        problems.append(f"{len(funds)} funds for {len(ids)} portfolio ids")
    for fund in funds:
        if fund.find("FundDynamicData/Portfolios") is not None:
            problems.append("portfolio under FundDynamicData")
        classes = fund.findall("SingleFund/ShareClasses/ShareClass")
        if len(classes) != 1:
            problems.append(f"{len(classes)} share classes in a fund")
            continue
        if classes[0].find("Portfolios/Portfolio/Positions/Position") is None:
            problems.append("share class without positions")
        sc_ids = {(e.text or "").strip() for e in classes[0].iterfind("Identifiers//*")}
        if not sc_ids & ids:
            problems.append(f"share class ids {sorted(sc_ids)} are no TPT portfolio id")
    return sorted(set(problems))


def _summary(report: dict[str, dict]) -> dict:
    ok = {k: e for k, e in report.items() if "error" not in e}
    out: dict = {
        "files": len(report),
        "readErrors": {k: e["error"] for k, e in report.items() if "error" in e},
        "versions": dict(Counter(e["version"] for e in ok.values())),
        "rows": sum(e["rows"] for e in ok.values()),
    }
    for mode in ("block", "core"):
        entries = {k: e[mode] for k, e in ok.items() if mode in e}
        xsd_errors: Counter = Counter()
        for e in entries.values():
            for msg in e["xsdErrors"]:
                xsd_errors[msg.split(":", 1)[-1].strip()[:160]] += 1
        diff_fields: Counter = Counter()
        added: Counter = Counter()
        for e in entries.values():
            diff_fields.update(e["diffFields"])
            added.update(e["added"])
        out[mode] = {
            "xsdInvalid": sorted(k for k, e in entries.items() if not e["xsdValid"]),
            "xsdErrorTypes": dict(xsd_errors.most_common(15)),
            "structureProblems": {k: e["structure"] for k, e in entries.items() if e["structure"]},
            "lossless": sum(1 for e in entries.values() if not e["diffs"]),
            "withDiffs": {k: e["diffs"] for k, e in entries.items() if e["diffs"]},
            "diffFields": dict(diff_fields.most_common(20)),
            "addedFields": dict(added.most_common()),
        }
    val = [e["validation"] for e in ok.values() if "validation" in e]
    both = [v for v in val if "errors" in v["source"] and "errors" in v["roundtrip"]]
    new_rules: Counter = Counter()
    gone_rules: Counter = Counter()
    for v in both:
        a, b = set(v["source"]["rules"]), set(v["roundtrip"]["rules"])
        new_rules.update(b - a)
        gone_rules.update(a - b)
    out["validation"] = {
        "validated": len(both),
        "failures": [k for k, e in ok.items() if "validation" in e and e["validation"] not in both][:20],
        "sourceErrors": sum(v["source"]["errors"] for v in both),
        "roundtripErrors": sum(v["roundtrip"]["errors"] for v in both),
        "sourceWarnings": sum(v["source"]["warnings"] for v in both),
        "roundtripWarnings": sum(v["roundtrip"]["warnings"] for v in both),
        "filesMoreErrors": sum(1 for v in both if v["roundtrip"]["errors"] > v["source"]["errors"]),
        "filesFewerErrors": sum(1 for v in both if v["roundtrip"]["errors"] < v["source"]["errors"]),
        "rulesOnlyInRoundtrip": dict(new_rules.most_common(25)),
        "rulesOnlyInSource": dict(gone_rules.most_common(25)),
    }
    return out


if __name__ == "__main__":
    main()
