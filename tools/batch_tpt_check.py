"""Convert a folder of FundsXML 4 files to TPT and check the results.

For every ``*.xml`` below the input folder (``*_REPLY.xml`` skipped):

* FundsXML → TPT for each requested version, written as xlsx to
  ``<out>/<version>/``;
* share class check: every TPT portfolio (field 1) must be a share class ISIN
  of the source file, and every share class must be reported or skipped with
  a ``shareclass_no_portfolio`` issue;
* validation with findatex-validator's web API (``POST /api/validate``).

Findings are aggregated per file and rule into ``<out>/report.json``; a summary
is printed.

Usage: python tools/batch_tpt_check.py [input] [--out DIR] [--validator URL]
       [--versions V7 V8] [--profiles SOLVENCY_II] [--no-validate] [--only PATTERN]
       [--retry-failed]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import httpx  # noqa: E402

from app.convert.to_tpt import extract_tpt  # noqa: E402
from app.ingest.fundsxml_reader import parse_fundsxml  # noqa: E402
from app.writers.tpt_writer import write_xlsx  # noqa: E402

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("input", nargs="?", default=str(ROOT / "testfiles" / "fundsxml"))
    ap.add_argument("--out", default=str(ROOT / "testfiles" / "tpt_out"))
    ap.add_argument("--validator", default="http://127.0.0.1:18082")
    ap.add_argument("--versions", nargs="+", default=["V7", "V8"])
    ap.add_argument("--profiles", nargs="+", default=["SOLVENCY_II"])
    ap.add_argument("--no-validate", action="store_true")
    ap.add_argument("--only", default="", help="substring filter on the relative path")
    ap.add_argument("--jobs", type=int, default=4, help="parallel validator requests")
    ap.add_argument(
        "--retry-failed",
        action="store_true",
        help="only the files whose validation failed in <out>/report.json; results are merged into it",
    )
    args = ap.parse_args()

    src, out = Path(args.input), Path(args.out)
    files = sorted(
        p
        for p in src.rglob("*.xml")
        if not p.name.endswith("_REPLY.xml")
        and ".DAV" not in p.parts
        and args.only in str(p.relative_to(src))
    )
    report: dict[str, dict] = {}
    if args.retry_failed:
        report = json.loads((out / "report.json").read_text())["files"]
        failed = {
            rel
            for rel, e in report.items()
            if "error" in e or any(_unvalidated(e.get(v, {})) for v in args.versions)
        }
        files = [p for p in files if str(p.relative_to(src)) in failed]
        for p in files:
            report.pop(str(p.relative_to(src)))
    for v in args.versions:
        (out / v).mkdir(parents=True, exist_ok=True)

    pool = ThreadPoolExecutor(max_workers=args.jobs)
    client = httpx.Client(timeout=900)
    pending = []
    started = time.time()
    for n, path in enumerate(files, 1):
        rel = str(path.relative_to(src))
        entry: dict = report.setdefault(rel, {})
        try:
            root = parse_fundsxml(path.read_bytes())
            classes = _share_classes(root)
            entry["shareClasses"] = len(classes)
            for v in args.versions:
                extract = extract_tpt(root, v)
                res = entry.setdefault(v, {})
                res["rows"] = len(extract.rows)
                res["portfolios"] = sorted({r.get("1", "") for r in extract.rows})
                res["issues"] = dict(Counter(f"{i.level}:{i.code}" for i in extract.issues))
                res["shareClassCheck"] = _check_share_classes(classes, extract)
                if not extract.rows:
                    continue
                target = out / v / (rel.replace("/", "__").removesuffix(".xml") + f"_TPT_{v}.xlsx")
                target.write_bytes(write_xlsx(extract.rows, v))
                res["file"] = str(target.relative_to(out))
                if not args.no_validate:
                    pending.append(pool.submit(_validate, client, args, target, v, res))
            del root
        except Exception as exc:  # noqa: BLE001 – report and carry on with the next file
            entry["error"] = f"{type(exc).__name__}: {exc}"
            entry["trace"] = traceback.format_exc(limit=5)
        print(f"[{n}/{len(files)}] {rel}  {time.time() - started:.0f}s", file=sys.stderr, flush=True)
    for f in pending:
        f.result()
    pool.shutdown()

    summary = _summary(report, args.versions)
    (out / "report.json").write_text(
        json.dumps({"summary": summary, "files": report}, indent=1, ensure_ascii=False)
    )
    print(json.dumps(summary, indent=1, ensure_ascii=False))


def _unvalidated(res: dict) -> bool:
    """A converted file whose validation failed or never came back."""
    return bool(res.get("rows")) and "errors" not in res.get("validation", {})


def _share_classes(root) -> dict[str, bool]:
    """ISIN of every share class → whether it has its own portfolio."""
    out = {}
    for sc in root.iterfind("Funds/Fund/SingleFund/ShareClasses/ShareClass"):
        isin = (sc.findtext("Identifiers/ISIN") or "").strip()
        out[isin or "?"] = sc.find("Portfolios/Portfolio") is not None
    return out


def _check_share_classes(classes: dict[str, bool], extract) -> list[str]:
    problems = []
    reported = {r.get("1", "") for r in extract.rows}
    skipped = {
        i.params.get("shareclass")
        for i in extract.issues
        if i.code in ("shareclass_no_portfolio", "shareclass_inactive")
    }
    for code in sorted(reported - set(classes)):
        problems.append(f"portfolio {code!r} is not a share class ISIN")
    for isin in sorted(set(classes) - reported - skipped):
        problems.append(f"share class {isin} neither reported nor skipped")
    if any(r.get("2") != "1" for r in extract.rows):
        problems.append("field 2 is not 1 (ISIN) in every row")
    return problems


def _validate(client: httpx.Client, args, path: Path, version: str, res: dict) -> None:
    data = {
        "templateId": "TPT",
        "templateVersion": f"{version}.0",
        "externalEnabled": "false",
        "profiles": args.profiles,
    }
    # Generous retries: a crashed validator needs a while to come back.
    for attempt in range(8):
        try:
            with path.open("rb") as fh:
                r = client.post(
                    f"{args.validator}/api/validate", data=data, files={"file": (path.name, fh, XLSX)}
                )
        except httpx.HTTPError as exc:
            res["validation"] = {"error": f"{type(exc).__name__}: {exc}"}
            time.sleep(5 * (attempt + 1))
            continue
        if r.status_code in (429, 503):
            time.sleep(5 * (attempt + 1))
            continue
        if r.status_code != 200:
            res["validation"] = {"error": f"HTTP {r.status_code}: {r.text[:300]}"}
            return
        body = r.json()
        rules: dict[str, dict] = {}
        for f in body.get("findings", []):
            key = f"{f.get('severity')}|{f.get('ruleId')}"
            agg = rules.setdefault(
                key, {"count": 0, "field": f.get("fieldNum"), "fieldName": f.get("fieldName"), "sample": None}
            )
            agg["count"] += 1
            if agg["sample"] is None:
                agg["sample"] = {
                    "message": f.get("message"),
                    "value": f.get("value"),
                    "row": f.get("rowIndex"),
                    "instrument": f.get("instrumentCode"),
                }
        s = body.get("summary", {})
        res["validation"] = {
            "errors": s.get("errorCount", 0),
            "warnings": s.get("warningCount", 0),
            "infos": s.get("infoCount", 0),
            "scores": {x["dimension"]: x["percentage"] for x in body.get("scores", [])},
            "rules": rules,
        }
        return


def _summary(report: dict[str, dict], versions: list[str]) -> dict:
    out: dict = {
        "files": len(report),
        "conversionErrors": {k: v["error"] for k, v in report.items() if "error" in v},
    }
    for v in versions:
        entries = [e[v] for e in report.values() if v in e]
        rules: Counter = Counter()
        rule_files: Counter = Counter()
        fields: dict[str, str] = {}
        issues: Counter = Counter()
        for e in entries:
            issues.update(e.get("issues", {}))
            for key, agg in e.get("validation", {}).get("rules", {}).items():
                rules[key] += agg["count"]
                rule_files[key] += 1
                fields[key] = f"{agg['field']} {agg['fieldName'] or ''}".strip()
        val = [e["validation"] for e in entries if "errors" in e.get("validation", {})]
        out[v] = {
            "converted": sum(1 for e in entries if e.get("rows")),
            "empty": sorted(k for k, e in report.items() if v in e and not e[v].get("rows")),
            "validated": len(val),
            "validationFailures": sum(1 for e in entries if "error" in e.get("validation", {})),
            "filesWithErrors": sum(1 for x in val if x["errors"]),
            "errors": sum(x["errors"] for x in val),
            "warnings": sum(x["warnings"] for x in val),
            "shareClassProblems": {
                k: e[v]["shareClassCheck"]
                for k, e in report.items()
                if v in e and e[v].get("shareClassCheck")
            },
            "converterIssues": dict(issues.most_common()),
            "rules": [
                {"rule": k, "field": fields[k], "findings": n, "files": rule_files[k]}
                for k, n in rules.most_common()
            ],
        }
    return out


if __name__ == "__main__":
    main()
