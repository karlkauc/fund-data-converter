"""openfunds → FundsXML → openfunds over folders of openfunds files.

Every step goes through ``app.service.convert`` with an explicit direction, like the web app. The
openfunds file read back is compared with the source field by field: share classes by ISIN
(OFST020000), holdings by share class, date and instrument (OFPH000100, else the name OFPH000200),
the n-th equal holding with the n-th. Non-openfunds columns (``TPT_…`` and the like) count too.

Besides the comparison the report keeps, per file, whether the FundsXML was schema-valid and the
issue codes of both steps.

Real openfunds files are rare, so ``--generate`` first writes one per TPT and FundsXML source
(``tpt-to-openfunds`` / ``fundsxml-to-openfunds``) into ``--generated`` and tests those as well.
Such files only exercise the mapping, not the reading of foreign openfunds files.

Usage: python tools/batch_openfunds_roundtrip.py [inputs ...] [--generate [SOURCES ...]] [--out DIR]
       [--only PATTERN] [--workers N] [--keep]
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
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tools"))

from app.ingest.openfunds_reader import looks_like_openfunds, read_openfunds  # noqa: E402
from app.service import Request, convert  # noqa: E402
from batch_tpt_roundtrip import _same  # noqa: E402

# FundsXML has one NAV date: a number-of-shares date without an AuM date comes back as the latter.
SAME_DATE = (("OFDY000066", "OFDY000061"), ("OFDY000076", "OFDY000071"))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("inputs", nargs="*", default=[str(ROOT / "testfiles" / "openfunds")])
    ap.add_argument(
        "--generate",
        nargs="*",
        metavar="SOURCE",
        help="write openfunds files from these TPT/FundsXML folders first (default: testfiles/tpt and "
        "testfiles/fundsxml)",
    )
    ap.add_argument("--generated", default=str(ROOT / "testfiles" / "openfunds_generated"))
    ap.add_argument("--out", default=str(ROOT / "testfiles" / "openfunds_roundtrip"))
    ap.add_argument("--only", default="", help="substring filter on the path")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument(
        "--keep",
        action="store_true",
        help="keep the FundsXML and the openfunds read back",
    )
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    inputs = [Path(p) for p in args.inputs if Path(p).exists()]
    if args.generate is not None:
        sources = args.generate or [
            str(ROOT / "testfiles" / "tpt"),
            str(ROOT / "testfiles" / "fundsxml"),
        ]
        gen = Path(args.generated)
        gen.mkdir(parents=True, exist_ok=True)
        _generate(
            [p for s in sources for p in _files(Path(s), (".xlsx", ".csv", ".xml"), args.only)],
            gen,
            args,
        )
        inputs.append(gen)
    files = [
        p
        for inp in inputs
        for p in _files(inp, (".xlsx", ".csv", ".zip"), args.only)
        if looks_like_openfunds(p.read_bytes(), p.name)
    ]
    print(f"{len(files)} openfunds files", file=sys.stderr, flush=True)

    report: dict[str, dict] = {}
    started = time.time()
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        tasks = [pool.submit(_check_file, p, out, args.keep) for p in files]
        for task in as_completed(tasks):
            rel, entry = task.result()
            report[rel] = entry
            print(
                f"[{len(report)}/{len(files)}] {rel}  {time.time() - started:.0f}s",
                file=sys.stderr,
                flush=True,
            )
            if len(report) % 50 == 0:
                _write_report(out, report, len(files), started)
    summary = _write_report(out, report, len(files), started)
    print(json.dumps(summary, indent=1, ensure_ascii=False, default=str))


def _files(inp: Path, suffixes: tuple[str, ...], only: str) -> list[Path]:
    cands = [inp] if inp.is_file() else sorted(inp.rglob("*"))
    return [
        p
        for p in cands
        if p.is_file()
        and p.suffix.lower() in suffixes
        and ".DAV" not in p.parts
        and "backup_" not in str(p)
        and only in str(p)
        and not p.name.upper().endswith("_REPLY.XML")
    ]


def _rel(path: Path) -> str:
    return str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)


def _step(data: bytes, filename: str, direction: str) -> tuple[bytes, str, dict]:
    report, res = convert(Request(data, filename, direction=direction, preview=False))
    body, name = res.data, res.filename
    if res.zipped:
        with zipfile.ZipFile(io.BytesIO(body)) as z:
            name = z.namelist()[0]
            body = z.read(name)
    validation = report.get("validation") or {}
    info = {
        "issueCodes": dict(Counter(f"{i['level']}:{i['code']}" for i in report["issues"])),
        "dataLoss": report.get("dataLoss"),
    }
    if validation:
        info["valid"] = validation.get("valid")
        info["validationErrors"] = (validation.get("errors") or [])[:5]
    return body, name, info


# -- generating openfunds files ------------------------------------------------------


def _generate(sources: list[Path], gen: Path, args) -> None:
    todo = [p for p in sources if not _generated_name(p, gen).exists() and _is_source(p)]
    print(
        f"generating {len(todo)} openfunds files into {gen}",
        file=sys.stderr,
        flush=True,
    )
    errors: dict[str, str] = {}
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        tasks = {pool.submit(_generate_one, p, gen): p for p in todo}
        for n, task in enumerate(as_completed(tasks), 1):
            if err := task.result():
                errors[_rel(tasks[task])] = err
            if n % 50 == 0:
                print(f"  generated {n}/{len(todo)}", file=sys.stderr, flush=True)
    (gen / "generate_errors.json").write_text(json.dumps(errors, indent=1, ensure_ascii=False))


def _is_source(path: Path) -> bool:
    if path.suffix.lower() != ".xml":
        return True
    with path.open("rb") as f:
        return b"<FundsXML4" in f.read(4096)


def _generated_name(src: Path, gen: Path) -> Path:
    kind = "fx" if src.suffix.lower() == ".xml" else "tpt"
    return gen / f"{kind}__{src.stem}_openfunds.xlsx"


def _generate_one(src: Path, gen: Path) -> str | None:
    kind = "fundsxml" if src.suffix.lower() == ".xml" else "tpt"
    try:
        body, _name, _ = _step(src.read_bytes(), src.name, f"{kind}-to-openfunds")
    except Exception as exc:  # noqa: BLE001 – report and carry on
        return f"{type(exc).__name__}: {exc}"
    _generated_name(src, gen).write_bytes(body)
    return None


# -- the round trip -----------------------------------------------------------------


def _check_file(path: Path, out: Path, keep: bool) -> tuple[str, dict]:
    rel = _rel(path)
    entry: dict = {}
    data = path.read_bytes()
    try:
        src = read_openfunds(data, path.name)
        entry.update(
            shareclasses=len(src.shareclasses),
            holdings=len(src.holdings),
            readIssues=dict(Counter(f"{i.level}:{i.code}" for i in src.issues)),
        )
        xml, xml_name, to_fx = _step(data, path.name, "openfunds-to-fundsxml")
        entry["toFundsxml"] = to_fx
        back_data, back_name, to_of = _step(xml, xml_name, "fundsxml-to-openfunds")
        entry["toOpenfunds"] = to_of
        if keep:
            work = out / re.sub(r"[^\w.-]+", "_", rel.rsplit(".", 1)[0])
            work.mkdir(parents=True, exist_ok=True)
            (work / xml_name).write_bytes(xml)
            (work / back_name).write_bytes(back_data)
        back = read_openfunds(back_data, back_name)
    except Exception as exc:  # noqa: BLE001
        entry["error"] = f"{type(exc).__name__}: {exc}"
        entry["trace"] = traceback.format_exc(limit=6)
        return rel, entry
    entry["shareclassesBack"] = len(back.shareclasses)
    entry["holdingsBack"] = len(back.holdings)
    sc = _compare(
        _by_key(src.shareclasses, _sc_key),
        _by_key(back.shareclasses, _sc_key),
        shareclass=True,
    )
    ho = _compare(_by_key(src.holdings, _holding_key), _by_key(back.holdings, _holding_key))
    entry["shareclassDiff"] = sc
    entry["holdingDiff"] = ho
    entry["lossless"] = not (sc["lost"] or sc["changed"] or sc["missingRecords"]) and not (
        ho["lost"] or ho["changed"] or ho["missingRecords"]
    )
    return rel, entry


def _fields(rec) -> dict[str, str]:
    values = {k: v for k, v in rec.values.items() if (v or "").strip()}
    values |= {f"extra:{k}": v for k, v in rec.extra.items() if (v or "").strip()}
    return values


def _sc_key(rec) -> str:
    return rec.values.get("OFST020000", "") or "?"


def _holding_key(rec) -> str:
    v = rec.values
    inst = v.get("OFPH000100") or v.get("OFPH000200") or "?"
    return f"{v.get('OFST020000', '')}|{v.get('OFPH000010', '')}|{inst}|{v.get('OFPH000400', '')}"


def _by_key(records, key) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    seen: Counter = Counter()
    for rec in records:
        k = key(rec)
        seen[k] += 1
        out[k if seen[k] == 1 else f"{k}#{seen[k]}"] = _fields(rec)
    return out


def _compare(src: dict[str, dict], back: dict[str, dict], shareclass: bool = False) -> dict:
    lost: Counter = Counter()
    changed: Counter = Counter()
    added: Counter = Counter()
    sample: list[str] = []
    for key, orig in src.items():
        got = back.get(key)
        if got is None:
            continue
        if shareclass:
            for nos, aum in SAME_DATE:
                if nos in orig and nos not in got and aum in got:
                    got = got | {nos: got[aum]}
        for field, value in orig.items():
            if field not in got:
                lost[field] += 1
                if len(sample) < 15:
                    sample.append(f"{key} {field}: {value} → (leer)")
            elif not _same(value, got[field]):
                changed[field] += 1
                if len(sample) < 15:
                    sample.append(f"{key} {field}: {value} → {got[field]}")
        for field in got.keys() - orig.keys():
            added[field] += 1
    return {
        "records": len(src),
        "missingRecords": len(src.keys() - back.keys()),
        "extraRecords": len(back.keys() - src.keys()),
        "missingSample": sorted(src.keys() - back.keys())[:5],
        "lost": sum(lost.values()),
        "changed": sum(changed.values()),
        "added": sum(added.values()),
        "lostFields": dict(lost.most_common()),
        "changedFields": dict(changed.most_common()),
        "addedFields": dict(added.most_common()),
        "sample": sample,
    }


# -- report -------------------------------------------------------------------------


def _summary(report: dict[str, dict]) -> dict:
    ok = [e for e in report.values() if "error" not in e]
    agg: dict = {}
    for part in ("shareclassDiff", "holdingDiff"):
        a: dict = {
            "records": 0,
            "missingRecords": 0,
            "extraRecords": 0,
            "lost": 0,
            "changed": 0,
            "added": 0,
        }
        fields = {
            "lostFields": Counter(),
            "changedFields": Counter(),
            "addedFields": Counter(),
        }
        files_with = {"lostFields": Counter(), "changedFields": Counter()}
        for e in ok:
            d = e[part]
            for k in a:
                a[k] += d[k]
            for k, counter in fields.items():
                counter.update(d[k])
            for k, counter in files_with.items():
                counter.update(d[k].keys())
        a |= {k: dict(v.most_common(40)) for k, v in fields.items()}
        a |= {f"filesWith_{k}": dict(v.most_common(40)) for k, v in files_with.items()}
        agg[part] = a
    return {
        "files": len(report),
        "errors": dict(Counter(e["error"].split("\n")[0][:160] for e in report.values() if "error" in e)),
        "errorFiles": sorted(k for k, e in report.items() if "error" in e)[:50],
        "lossless": sum(1 for e in ok if e["lossless"]),
        "fundsxmlInvalid": sum(1 for e in ok if e["toFundsxml"].get("valid") is False),
        "invalidFiles": sorted(
            k for k, e in report.items() if "error" not in e and e["toFundsxml"].get("valid") is False
        )[:50],
        "validationErrors": dict(
            Counter(
                re.sub(r"\[\d+\]", "", err)[:200]
                for e in ok
                for err in set(e["toFundsxml"].get("validationErrors") or [])
            ).most_common(30)
        ),
        "toFundsxmlIssues": dict(
            sum((Counter(e["toFundsxml"]["issueCodes"]) for e in ok), Counter()).most_common(30)
        ),
        "readIssues": dict(sum((Counter(e["readIssues"]) for e in ok), Counter()).most_common(30)),
        **agg,
    }


def _write_report(out: Path, report: dict[str, dict], total: int, started: float) -> dict:
    summary = {
        "progress": f"{len(report)}/{total}",
        "elapsedSeconds": round(time.time() - started),
    }
    summary |= _summary(report)
    body = json.dumps(
        {"summary": summary, "files": dict(sorted(report.items()))},
        indent=1,
        ensure_ascii=False,
    )
    tmp = out / ".report.json.tmp"
    tmp.write_text(body)
    tmp.replace(out / "report.json")
    return summary


if __name__ == "__main__":
    main()
