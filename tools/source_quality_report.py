"""Source data quality report for the FundsXML and TPT test files (German HTML + CSV).

Two steps:

``collect``
    * FundsXML sources (``testfiles/fundsxml``): XSD check of the source,
      conversion to TPT V7 and V8 and validation of both with
      findatex-validator.
    * TPT sources (``testfiles/tpt``): validation of the source file, and
      what the source lacks for a valid FundsXML document (core structures).

    One gzip JSON per source file goes to ``<out>/raw/<kind>/``. A file whose
    raw JSON is complete is skipped, so running ``collect`` again repeats only
    what failed.

``build``
    Aggregates the raw files into ``<out>/quellqualitaet.html`` and the CSV
    lists ``<out>/befunde_fehler.csv`` and ``<out>/befunde_warnungen.csv``.
    A finding is counted once per file and instrument: a fund portfolio
    repeated for several share classes counts once.

Usage: python tools/source_quality_report.py collect [--validator URL] [--jobs 1] [--workers 4] [--only S]
       python tools/source_quality_report.py build
"""

from __future__ import annotations

import argparse
import base64
import csv
import gzip
import json
import re
import sys
import time
import traceback
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import httpx  # noqa: E402
from validator_client import ValidatorError, post  # noqa: E402

from app.api.mapping import _CTX_PREFIX  # noqa: E402
from app.convert.to_fundsxml import ConvertOptions, convert_tpt_to_fundsxml, group_portfolios  # noqa: E402
from app.convert.to_tpt import extract_tpt  # noqa: E402
from app.ingest.fundsxml_reader import parse_fundsxml  # noqa: E402
from app.ingest.tpt_reader import read_tpt  # noqa: E402
from app.mapping.rules import CORE_RULES  # noqa: E402
from app.spec.catalog import load_catalog  # noqa: E402
from app.validate.xsd import validate_fundsxml  # noqa: E402
from app.writers.tpt_writer import write_xlsx  # noqa: E402

TESTFILES = ROOT / "testfiles"
SOURCES = {"fundsxml": TESTFILES / "fundsxml", "tpt": TESTFILES / "tpt"}
TEMPLATE = Path(__file__).with_name("source_quality_report.html")
# Validator row index of the first data row (row 1 = first TPT position).
FIRST_ROW = 1
EXAMPLES = {"ERROR": 25, "WARNING": 10, "INFO": 5}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=("collect", "build"))
    ap.add_argument("--out", default=str(TESTFILES / "report"))
    ap.add_argument("--validator", default="http://127.0.0.1:18113")
    ap.add_argument("--profiles", nargs="+", default=["SOLVENCY_II"])
    ap.add_argument("--jobs", type=int, default=1, help="parallel validator requests")
    ap.add_argument("--workers", type=int, default=4, help="parallel conversion processes")
    ap.add_argument("--only", default="", help="substring filter on the relative path")
    args = ap.parse_args()
    out = Path(args.out)
    if args.step == "collect":
        collect(args, out)
    else:
        build(out)


# ---------------------------------------------------------------- collect


def _sources(only: str) -> list[tuple[str, Path, str]]:
    found = []
    for kind, src in SOURCES.items():
        suffixes = (".xml",) if kind == "fundsxml" else (".xlsx", ".csv")
        for p in sorted(src.rglob("*")):
            rel = str(p.relative_to(src))
            if (
                p.is_file()
                and p.suffix.lower() in suffixes
                and not p.name.endswith("_REPLY.xml")
                and ".DAV" not in p.parts
                and only in rel
            ):
                found.append((kind, p, rel))
    return found


def _raw_path(out: Path, kind: str, rel: str) -> Path:
    return out / "raw" / kind / (rel.replace("/", "__") + ".json.gz")


def _complete(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        data = _load(path)
    except (OSError, ValueError, EOFError):
        return False
    return "error" not in data and all("findings" in v for v in data["versions"].values())


def _load(path: Path) -> dict:
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return json.load(fh)


def collect(args, out: Path) -> None:
    tmp = out / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    todo = [(k, p, rel) for k, p, rel in _sources(args.only) if not _complete(_raw_path(out, k, rel))]
    print(f"{len(todo)} file(s) to collect", file=sys.stderr, flush=True)
    client = httpx.Client(timeout=900)
    started = time.time()
    done = Counter()
    with ProcessPoolExecutor(max_workers=args.workers) as workers, ThreadPoolExecutor(args.jobs) as pool:
        jobs = {
            workers.submit(_fundsxml_job if k == "fundsxml" else _tpt_job, p, rel, tmp): (k, rel)
            for k, p, rel in todo
        }
        pending = []
        for task in as_completed(jobs):
            kind, rel = jobs[task]
            try:
                data = task.result()
            except Exception as exc:  # noqa: BLE001 – a crashed worker is reported like a failed file
                data = {"kind": kind, "rel": rel, "versions": {}, "error": f"{type(exc).__name__}: {exc}"}
            pending.append(
                pool.submit(_validate_and_store, client, args, out, data, done, started, len(todo))
            )
        for f in pending:
            f.result()
    print(f"done: {dict(done)}", file=sys.stderr)


def _validate_and_store(
    client, args, out: Path, data: dict, done: Counter, started: float, total: int
) -> None:
    for version, entry in data["versions"].items():
        file = Path(entry.pop("validate", ""))
        if not file.name:
            continue
        try:
            body = post(client, args.validator, file, version, args.profiles)
            entry["findings"] = [
                [
                    f.get("severity"),
                    f.get("ruleId"),
                    f.get("fieldNum"),
                    f.get("message"),
                    f.get("value"),
                    f.get("rowIndex"),
                    f.get("instrumentCode"),
                ]
                for f in body.get("findings", [])
            ]
            entry["fieldNames"] = {
                str(f.get("fieldNum")): f.get("fieldName")
                for f in body.get("findings", [])
                if f.get("fieldNum")
            }
            s = body.get("summary", {})
            entry["summary"] = {k: s.get(k) for k in ("errorCount", "warningCount", "infoCount")}
        except ValidatorError as exc:
            entry["validationError"] = str(exc)
        finally:
            if file.parent.name == "tmp":
                file.unlink(missing_ok=True)
    target = _raw_path(out, data["kind"], data["rel"])
    target.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(target, "wt", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))
    ok = "error" not in data and all("findings" in v for v in data["versions"].values())
    done["ok" if ok else "failed"] += 1
    n = sum(done.values())
    print(
        f"[{n}/{total}] {data['kind']} {data['rel']}  {time.time() - started:.0f}s",
        file=sys.stderr,
        flush=True,
    )


def _fundsxml_job(path: Path, rel: str, tmp: Path) -> dict:
    data: dict = {"kind": "fundsxml", "rel": rel, "versions": {}}
    try:
        root = parse_fundsxml(path.read_bytes())
        data["supplier"] = (
            root.findtext("ControlData/DataSupplier/Name")
            or root.findtext("ControlData/DataSupplier/Short")
            or ""
        ).strip()
        data["contentDate"] = (root.findtext("ControlData/ContentDate") or "").strip()
        valid, errors = validate_fundsxml(root)
        data["xsd"] = {"valid": valid, "errors": len(errors), "sample": errors[:20]}
        classes = root.findall("Funds/Fund/SingleFund/ShareClasses/ShareClass")
        data["shareClasses"] = len(classes)
        data["shareClassesWithPortfolio"] = sum(
            1 for sc in classes if sc.find("Portfolios/Portfolio") is not None
        )
        data["funds"] = [
            (f.findtext("Names/OfficialName") or "").strip() for f in root.iterfind("Funds/Fund")
        ][:20]
        for version in ("V7", "V8"):
            extract = extract_tpt(root, version)
            entry = data["versions"][version] = {
                "rows": len(extract.rows),
                "issues": [[i.level, i.code, i.params or {}] for i in extract.issues],
            }
            if version == "V7":
                data["rowInfo"] = [[r.get("1", ""), r.get("14", ""), r.get("17", "")] for r in extract.rows]
            if extract.rows:
                target = tmp / f"{abs(hash((rel, version)))}_{version}.xlsx"
                target.write_bytes(write_xlsx(extract.rows, version))
                entry["validate"] = str(target)
    except Exception as exc:  # noqa: BLE001
        data["error"] = f"{type(exc).__name__}: {exc}"
        data["trace"] = traceback.format_exc(limit=5)
    return data


_POSITION = re.compile(r"^/Funds/Fund(?:\[(\d+)\])?/.*?/Positions/Position(?:\[(\d+)\])?")
_FUND = re.compile(r"^/Funds/Fund(?:\[(\d+)\])?/")


def _tpt_job(path: Path, rel: str, tmp: Path) -> dict:
    data: dict = {"kind": "tpt", "rel": rel, "versions": {}}
    try:
        doc = read_tpt(path.read_bytes(), path.name)
        names = Counter(r.get("117") for r in doc.rows if r.get("117"))
        data["supplier"] = names.most_common(1)[0][0] if names else rel.split("/")[0] if "/" in rel else ""
        data["contentDate"] = next((r.get("6") for r in doc.rows if r.get("6")), "")
        data["funds"] = sorted({r.get("3") for r in doc.rows if r.get("3")})[:20]
        data["readerIssues"] = [[i.level, i.code, i.row, i.field, i.message] for i in doc.issues][:200]
        data["rowInfo"] = [[r.get("1") or "", r.get("14") or "", r.get("17") or ""] for r in doc.rows]
        res = convert_tpt_to_fundsxml(doc, ConvertOptions(include_block=False))
        data["xsd"] = {"valid": res.valid, "errors": len(res.validation_errors)}
        data["fundsxmlGaps"] = _fundsxml_gaps(doc, res.validation_errors)
        data["versions"][doc.version] = {"rows": len(doc.rows), "validate": str(path)}
    except Exception as exc:  # noqa: BLE001
        data["error"] = f"{type(exc).__name__}: {exc}"
        data["trace"] = traceback.format_exc(limit=5)
    return data


def _fundsxml_gaps(doc, errors: list[str]) -> list[list]:
    """XSD errors of the generated FundsXML, traced back to the TPT row.

    Each gap: [code, field, row, instrument, element, message].
    """
    groups = group_portfolios(doc.rows)
    index = {id(r): n for n, r in enumerate(doc.rows, 1)}  # the validator's row numbering
    gaps = []
    for err in errors:
        code, field = _gap_kind(err)
        if code == "ASSET_TYPE":
            continue  # same cause as the position's NO_TYPE gap
        row = None
        m = _POSITION.match(err)
        if m:
            group = groups[int(m.group(1) or 1) - 1]
            idx = int(m.group(2) or 1) - 1
            row = group.rows[idx] if idx < len(group.rows) else None
        elif (f := _FUND.match(err)) is not None:
            row = groups[int(f.group(1) or 1) - 1].rows[0]
        element = err.split(": Element '", 1)[1].split("'", 1)[0] if ": Element '" in err else ""
        parent = err.split(":", 1)[0].rsplit("/", 2)[-2] if err.count("/") > 1 else ""
        gaps.append(
            [
                code,
                field,
                index[id(row)] if row is not None else None,
                (row.get("14") or row.get("17") or "") if row is not None else "",
                parent if code in ("UNITS", "NOMINAL") else element,
                "" if code != "OTHER" else err.split(": ", 1)[-1][:300],
            ]
        )
    return gaps


def _gap_kind(err: str) -> tuple[str, str]:
    if "Expected is ( Units )" in err:
        return "UNITS", "18"
    if "Expected is ( Contracts )" in err:
        return "CONTRACTS", "18"
    if "Expected is ( Nominal )" in err:
        return "NOMINAL", "19"
    if "Expected is ( Shares )" in err:
        return "SHARES", "8b"
    if "'Asset': Missing child element(s). Expected is one of ( FISN, AssetType )" in err:
        return "ASSET_TYPE", "12"
    if "'CustomAttributes': This element is not expected" in err:
        return "NO_TYPE", "12"
    return "OTHER", ""


# ---------------------------------------------------------------- build

# Fields that describe the portfolio / share class, not a position.
PORTFOLIO_CTX = ("tpt_portfolio", "shareclass", "sc_nav", "sc_price", "fund", "fund_info", "nav", "control")

SEVERITY_DE = {"ERROR": "Fehler", "WARNING": "Warnung", "INFO": "Hinweis"}

# Explanations and fixes for known rules. Keys: exact rule id, "<KIND>/<field>" or the rule kind.
RULE_TEXT: dict[str, dict[str, str]] = {
    "PRESENCE": {
        "was": "Pflichtfeld für Solvency II fehlt.",
        "fix": "Feld befüllen.",
    },
    "COND_PRESENCE": {
        "was": "Bedingtes Pflichtfeld fehlt; für diesen Instrumenttyp (CIC) ist es erforderlich.",
        "fix": "Feld für die betroffenen Instrumente befüllen.",
    },
    "FORMAT": {
        "was": "Der Wert hat ein ungültiges Format oder ist kein erlaubter Code.",
        "fix": "Wert im vorgeschriebenen Format liefern (z. B. ISO-Ländercode, Datum JJJJ-MM-TT).",
    },
    "CLOSED_LIST": {
        "was": "Der Wert ist in der Codeliste der TPT-Spezifikation nicht enthalten.",
        "fix": "Einen Wert aus der Codeliste liefern.",
    },
    "ISIN": {
        "was": "Die Kennung ist als ISIN gekennzeichnet, ist aber keine gültige ISIN (Prüfziffer/Format).",
        "fix": "Gültige ISIN liefern oder die Kennung mit dem passenden Typ kennzeichnen.",
    },
    "LEI": {
        "was": "Der LEI ist ungültig (Länge, Zeichen oder Prüfziffer).",
        "fix": "Gültigen 20-stelligen LEI liefern; ohne LEI das Feld leer lassen.",
    },
    "XF-10/33": {
        "was": "Fest verzinstes Instrument (Feld 32 = Fixed) ohne Kupon (Feld 33).",
        "fix": "Kupon liefern (FundsXML: AssetDetails/Bond/Coupon/Rate) oder die Zinsart korrigieren.",
    },
    "XF-10/34": {
        "was": "Variabel verzinstes Instrument (Feld 32 = Floating) "
        "ohne Kennung des Referenzzinssatzes (Feld 34).",
        "fix": "Kennung des Referenzzinssatzes liefern "
        "(FundsXML: AssetDetails/Bond/Coupon/BaseIndex/Identifiers).",
    },
    "XF-10/35": {
        "was": "Variabel verzinstes Instrument ohne Typ der Referenzzins-Kennung (Feld 35).",
        "fix": "Kennung des Referenzzinssatzes samt Typ liefern.",
    },
    "XF-10/36": {
        "was": "Variabel verzinstes Instrument ohne Namen des Referenzzinssatzes (Feld 36).",
        "fix": "Namen des Referenzzinssatzes liefern, z. B. EURIBOR 3M "
        "(FundsXML: AssetDetails/Bond/Coupon/BaseIndex/Name).",
    },
    "XF-10/37": {
        "was": "Variabel verzinstes Instrument ohne Zinsaufschlag (Feld 37).",
        "fix": "Aufschlag auf den Referenzzinssatz liefern (FundsXML: AssetDetails/Bond/Coupon/Margin).",
    },
    "XF-14/UNDERLYING_CIC": {
        "was": "Bei Derivaten (Futures, Optionen) fehlt der CIC des Basiswerts (Feld 67).",
        "fix": "CIC des Basiswerts liefern.",
    },
    "XF-17/INDEX_NAME": {
        "was": "Eine Referenzzins-Kennung (Feld 34) ist angegeben, aber kein Name dazu (Feld 36).",
        "fix": "Namen des Referenzzinssatzes liefern (FundsXML: AssetDetails/Bond/Coupon/BaseIndex/Name).",
    },
    "XF-17/INDEX_MARGIN": {
        "was": "Eine Referenzzins-Kennung (Feld 34) ist angegeben, aber kein Zinsaufschlag (Feld 37).",
        "fix": "Aufschlag liefern, bei Aufschlag null den Wert 0.",
    },
    "XF-18/OPTION_DIRECTION": {
        "was": "Anleihe mit eingebettetem Kündigungsrecht (Feld 42 = CAL/PUT) "
        "ohne Angabe, wer es ausübt (Feld 44).",
        "fix": "Feld 44 liefern: Emittent oder Inhaber.",
    },
    "XF-19/STRIKE_PRICE": {
        "was": "Eingebettete Option (Feld 42) ohne Ausübungspreis (Feld 45).",
        "fix": "Ausübungspreis der eingebetteten Option liefern.",
    },
    "XF-05/CASH_PERCENTAGE": {
        "was": "Die gemeldete Kassaquote (Feld 9) passt nicht zur Summe der Kassapositionen (CIC xx7x).",
        "fix": "Kassaquote als Anteil (0–1) aus den Kassapositionen berechnen.",
    },
    "XF-06/NAV_PRICE_SHARES": {
        "was": "Nettovermögen (Feld 5) weicht von Anteilspreis × Anteile (Felder 8 × 8b) ab.",
        "fix": "NAV, Anteilspreis und Anteile zum selben Stichtag liefern.",
    },
    "XF-11/MATURITY_AFTER_REPORTING": {
        "was": "Das Fälligkeitsdatum (Feld 39) liegt vor dem Berichtsstichtag.",
        "fix": "Fällige Instrumente ausbuchen oder Fälligkeit korrigieren.",
    },
    "FORMAT/12": {
        "was": "Ungültiger CIC (2 Buchstaben + Ziffer/A–F + Zeichen, Länge 4).",
        "fix": "Gültigen CIC liefern (FundsXML: Asset/Classifications/Classification[ListedGroup=CIC]).",
    },
    "FORMAT/52": {
        "was": "Unbekannter ISO-3166-Ländercode des Emittenten (z. B. AN, 4J, 4W).",
        "fix": "Gültigen zweistelligen ISO-Ländercode liefern "
        "(FundsXML: Asset/Country bzw. Issuer/Address/Country).",
    },
    "FORMAT/131": {
        "was": "Kategorie des Basiswerts (Feld 131) nicht in der Codeliste (z. B. 3 statt 3L/3X).",
        "fix": "Wert aus der Codeliste liefern: 1, 2, 3L, 3X, 4 … F, L.",
    },
    "PRESENCE/23": {
        "was": "Clean Value in Kurswährung fehlt. "
        "Er lässt sich nur berechnen, wenn die Stückzinsen bekannt sind.",
        "fix": "Stückzinsen liefern (FundsXML: Position/Bond/AccruedInterest) oder den Clean Value direkt.",
    },
    "PRESENCE/25": {
        "was": "Clean Value in Portfoliowährung fehlt (Marktwert ohne Stückzinsen).",
        "fix": "Stückzinsen liefern (FundsXML: Position/Bond/AccruedInterest) oder den Clean Value direkt.",
    },
    "PRESENCE/22": {
        "was": "Marktwert in Kurswährung fehlt.",
        "fix": "Betrag in Positionswährung liefern (FundsXML: TotalValue/Amount[@ccy=Positionswährung]) "
        "oder einen Wechselkurs (Position/FXRates).",
    },
    "PRESENCE/27": {
        "was": "Marktexposure in Kurswährung fehlt.",
        "fix": "Exposure bzw. Wechselkurs liefern (FundsXML: Position/Exposures, Position/FXRates).",
    },
    "PRESENCE/28": {
        "was": "Marktexposure in Portfoliowährung fehlt (Derivat ohne Exposure).",
        "fix": "Exposure (Commitment) liefern (FundsXML: Position/Exposures/Exposure).",
    },
    "PRESENCE/30": {
        "was": "Exposure-Gewicht fehlt, weil das Exposure fehlt.",
        "fix": "Exposure liefern (FundsXML: Position/Exposures/Exposure).",
    },
    "PRESENCE/8b": {
        "was": "Anzahl der umlaufenden Anteile fehlt.",
        "fix": "FundsXML: ShareClass/TotalAssetValues/TotalAssetValue/SharesOutstanding.",
    },
    "PRESENCE/14": {
        "was": "Kennung des Instruments fehlt.",
        "fix": "ISIN oder eine interne Kennung liefern (FundsXML: Asset/Identifiers).",
    },
    "PRESENCE/17": {
        "was": "Name des Instruments fehlt.",
        "fix": "Bezeichnung liefern (FundsXML: Asset/Name), bei Konten z. B. Bank und Währung.",
    },
    "FUNDSXML/UNITS": {
        "was": "Stückzahl (Feld 18) fehlt. FundsXML verlangt sie für Aktien, Fonds und ähnliche Instrumente.",
        "fix": "Feld 18 (Quantity) im TPT liefern.",
    },
    "FUNDSXML/CONTRACTS": {
        "was": "Anzahl der Kontrakte (Feld 18) fehlt. FundsXML verlangt sie für Futures und Optionen.",
        "fix": "Feld 18 (Quantity) im TPT liefern.",
    },
    "FUNDSXML/NOMINAL": {
        "was": "Nominale (Feld 19) fehlt. FundsXML verlangt sie für Anleihen.",
        "fix": "Feld 19 (Nominal amount) im TPT liefern.",
    },
    "FUNDSXML/SHARES": {
        "was": "Anzahl umlaufender Anteile (Feld 8b) fehlt; FundsXML verlangt sie an der Anteilsklasse.",
        "fix": "Feld 8b im TPT liefern.",
    },
    "FUNDSXML/NO_TYPE": {
        "was": "Ohne CIC (Feld 12) kann kein Instrumenttyp bestimmt werden; "
        "die Position ist in FundsXML unvollständig.",
        "fix": "Gültigen CIC in Feld 12 liefern.",
    },
    "FUNDSXML/OTHER": {
        "was": "Sonstige FundsXML-Pflichtangabe fehlt.",
        "fix": "Siehe Meldung.",
    },
}

ISSUE_TEXT = {
    "shareclass_no_portfolio": "Anteilsklasse ohne eigenes und ohne Fondsportfolio – nicht gemeldet",
    "shareclass_inactive": "Anteilsklasse ohne Vermögen (inaktiv) – nicht gemeldet",
    "fx_derived": "Wechselkurs für die Anteilsklassenwährung abgeleitet",
    "fx_missing": "Kein Wechselkurs für die Anteilsklassenwährung – Marktwerte fehlen",
    "mandatory_missing": "TPT-Pflichtfeld fehlt in der Quelle",
    "no_positions": "Keine Positionen gefunden",
}


def _field_meta() -> tuple[dict[str, str], dict[str, list[str]], set[str]]:
    names = {}
    for version in ("V7", "V8"):
        for f in load_catalog(version).fields:
            # "44_Issuer_bearer_option_exercise" → "Issuer bearer option exercise"
            names.setdefault(f.num_key, re.sub(r"^\d+[a-z]?_", "", f.num_data).replace("_", " ").strip())
    paths: dict[str, list[str]] = defaultdict(list)
    portfolio = set()
    for rule in CORE_RULES:
        if rule.ctx.startswith("tpt_"):
            if rule.ctx == "tpt_portfolio":
                portfolio.add(rule.field)
            continue
        if rule.ctx in PORTFOLIO_CTX:
            portfolio.add(rule.field)
        p = _CTX_PREFIX[rule.ctx] + rule.path
        if p not in paths[rule.field]:
            paths[rule.field].append(p)
    for key in names:
        num = re.match(r"\d+", key)
        if num and (int(num.group()) <= 11 or 115 <= int(num.group()) <= 123):
            portfolio.add(key)
    portfolio.add("1000")
    return names, dict(paths), portfolio


def _rule_text(rule: str, field: str) -> dict[str, str]:
    kind = rule.split("/", 1)[0]
    for key in (rule, f"{kind}/{field}", "/".join(rule.split("/")[:2]), kind):
        if key in RULE_TEXT:
            return RULE_TEXT[key]
    return {"was": "", "fix": ""}


def build(out: Path) -> None:
    names, paths, portfolio_fields = _field_meta()
    files = []
    rules: dict[str, dict] = {}
    overview: list[list] = []
    per_file = out / "befunde"
    per_file.mkdir(parents=True, exist_ok=True)
    for raw in sorted((out / "raw").rglob("*.json.gz")):
        data = _load(raw)
        csv_rows: list[list] = []
        entry = _file_entry(data, names, portfolio_fields, rules, csv_rows, overview)
        entry["csv"] = f"befunde/{data['kind']}__{data['rel'].replace('/', '__')}.csv"
        _write_csv(out / entry["csv"], FILE_HEADER, csv_rows)
        files.append(entry)
    for key, r in rules.items():
        r.update(_rule_text(r["rule"], r["field"]))
        r["paths"] = paths.get(r["field"], [])[:4]
        r["fieldName"] = names.get(r["field"], r.get("fieldName") or "")
        r["files"] = len(r.pop("fileSet"))
        r["key"] = key
    roundtrip = _roundtrip_summary()
    payload = {
        "generated": date.today().isoformat(),
        "files": files,
        "rules": sorted(rules.values(), key=lambda r: (r["sev"] != "ERROR", -r["files"], -r["distinct"])),
        "measures": _measures(files, rules),
        "roundtrip": roundtrip,
        "sevText": SEVERITY_DE,
    }
    blob = base64.b64encode(
        gzip.compress(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode())
    )
    html = TEMPLATE.read_text(encoding="utf-8").replace("__DATA__", blob.decode())
    (out / "quellqualitaet.html").write_text(html, encoding="utf-8")
    _write_csv(out / "befunde_uebersicht.csv", OVERVIEW_HEADER, overview)
    print(
        f"{len(files)} files, {len(rules)} rules, html {len(html) / 1e6:.1f} MB, overview {len(overview)}",
        file=sys.stderr,
    )


OVERVIEW_HEADER = [
    "Richtung",
    "Lieferant",
    "Datei",
    "Version",
    "Schwere",
    "Regel",
    "Feld",
    "Feldname",
    "Ebene",
    "Instrumente",
    "Validator-Meldungen",
    "Beispiele",
    "Meldung",
]
FILE_HEADER = [
    "Schwere",
    "Regel",
    "Feld",
    "Feldname",
    "Ebene",
    "Instrument (Feld 14)",
    "Name (Feld 17)",
    "Wert",
    "Erste Zeile",
    "Anteilsklassen",
    "Meldung",
]


def _write_csv(path: Path, header: list[str], rows: list[list]) -> None:
    """Semicolon CSV with BOM, so Excel opens it with umlauts intact."""
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(header)
        w.writerows(rows)


def _file_entry(data: dict, names, portfolio_fields, rules: dict, csv_rows: list, overview: list) -> dict:
    """The report entry of one source file; fills its CSV rows and its lines of the overview CSV."""
    kind = data["kind"]
    rel = data["rel"]
    supplier = data.get("supplier") or "(unbekannt)"
    entry = {
        "kind": kind,
        "rel": rel,
        "supplier": supplier,
        "date": data.get("contentDate", ""),
        "funds": data.get("funds", []),
        "xsd": data.get("xsd"),
        "error": data.get("error"),
        "shareClasses": data.get("shareClasses"),
        "versions": {},
    }
    row_info = data.get("rowInfo", [])
    main = "V7" if "V7" in data["versions"] else next(iter(data["versions"]), None)
    entry["main"] = main
    groups_by_version = {}
    for version, v in data["versions"].items():
        # A TPT file may lack fund fields in single rows only, so its findings stay per row.
        groups = _aggregate(
            v.get("findings", []), row_info, portfolio_fields if kind == "fundsxml" else set()
        )
        groups_by_version[version] = groups
        entry["versions"][version] = {
            "rows": v.get("rows"),
            "validationError": v.get("validationError"),
            "raw": v.get("summary"),
            "errors": sum(len(g["items"]) for g in groups.values() if g["sev"] == "ERROR"),
            "warnings": sum(len(g["items"]) for g in groups.values() if g["sev"] == "WARNING"),
        }
        if kind == "fundsxml":
            issues = Counter()
            examples: dict[str, list] = defaultdict(list)
            for level, code, params in v.get("issues", []):
                issues[(level, code)] += 1
                if len(examples[code]) < 10 and params:
                    examples[code].append(params)
            if version == main:
                entry["issues"] = [
                    {
                        "level": lvl,
                        "code": code,
                        "n": n,
                        "text": ISSUE_TEXT.get(code, code),
                        "examples": examples[code],
                    }
                    for (lvl, code), n in issues.most_common()
                ]
    if kind == "tpt":
        gaps = _aggregate_gaps(data.get("fundsxmlGaps", []))
        if main:
            groups_by_version.setdefault(main, {}).update(gaps)
        entry["readerIssues"] = data.get("readerIssues", [])[:20]
    detail = []
    for key, g in sorted(
        groups_by_version.get(main, {}).items(),
        key=lambda kv: (kv[1]["sev"] != "ERROR", -len(kv[1]["items"])),
    ):
        sev, rule, field = key
        rk = f"{kind}|{sev}|{rule}|{field}"
        r = rules.setdefault(
            rk,
            {
                "kind": kind,
                "sev": sev,
                "rule": rule,
                "field": field,
                "fieldName": g.get("fieldName"),
                "message": g["message"],
                "distinct": 0,
                "raw": 0,
                "fileSet": set(),
            },
        )
        r["distinct"] += len(g["items"])
        r["raw"] += g["raw"]
        r["fileSet"].add(rel)
        items = sorted(g["items"].items(), key=lambda kv: kv[1][1] if kv[1][1] is not None else 0)
        detail.append(
            {
                "rule": rule,
                "sev": sev,
                "field": field,
                "level": g["level"],
                "distinct": len(items),
                "raw": g["raw"],
                "message": g["message"],
                "examples": [
                    [inst, val, row, len(sc), name]
                    for inst, (val, row, sc, name) in items[: EXAMPLES.get(sev, 10)]
                ],
            }
        )
        level = "Portfolio" if g["level"] == "portfolio" else "Position"
        sample = ", ".join(inst for inst, _ in items[:10]) + (" …" if len(items) > 10 else "")
        overview.append(
            [
                "FundsXML → TPT" if kind == "fundsxml" else "TPT",
                supplier,
                rel,
                main,
                SEVERITY_DE.get(sev, sev),
                rule,
                field,
                names.get(field, ""),
                level,
                len(items),
                g["raw"],
                sample,
                g["message"],
            ]
        )
        if sev == "ERROR":
            for inst, (val, row, sc, name) in items:
                csv_rows.append(
                    [
                        SEVERITY_DE[sev],
                        rule,
                        field,
                        names.get(field, ""),
                        level,
                        inst,
                        name,
                        val,
                        row,
                        len(sc),
                        g["message"],
                    ]
                )
        else:
            # Warnings are far more numerous: one line per rule with examples.
            csv_rows.append(
                [
                    SEVERITY_DE.get(sev, sev),
                    rule,
                    field,
                    names.get(field, ""),
                    level,
                    f"{len(items)} Instrumente: {sample}",
                    "",
                    "",
                    "",
                    "",
                    g["message"],
                ]
            )
    entry["rules"] = detail
    if kind == "fundsxml" and "V8" in groups_by_version and main == "V7":
        only_v8 = Counter()
        for (sev, rule, _field), g in groups_by_version["V8"].items():
            if (sev, rule, _field) not in groups_by_version["V7"]:
                only_v8[f"{SEVERITY_DE.get(sev, sev)} {rule}"] += len(g["items"])
        entry["v8Only"] = dict(only_v8)
    return entry


def _aggregate(findings: list[list], row_info: list[list], portfolio_fields: set[str]) -> dict:
    """Findings per (severity, rule, field), de-duplicated by instrument (or portfolio)."""
    groups: dict[tuple, dict] = {}
    for sev, rule, field, message, value, row, instrument in findings:
        field = str(field or "")
        key = (sev, rule, field)
        g = groups.get(key)
        if g is None:
            level = (
                "portfolio"
                if field in portfolio_fields or (not instrument and row in (None, 0))
                else "position"
            )
            g = groups[key] = {"sev": sev, "level": level, "raw": 0, "items": {}, "message": message}
        g["raw"] += 1
        info = (
            row_info[row - FIRST_ROW]
            if isinstance(row, int) and 0 <= row - FIRST_ROW < len(row_info)
            else None
        )
        share_class = info[0] if info else ""
        name = info[2] if info else ""
        dkey = (
            "Portfolio"
            if g["level"] == "portfolio"
            else (instrument or (info[1] if info else "") or f"Zeile {row}")
        )
        item = g["items"].get(dkey)
        if item is None:
            g["items"][dkey] = [value, row, {share_class}, name]
        else:
            item[2].add(share_class)
    return groups


def _aggregate_gaps(gaps: list[list]) -> dict:
    groups: dict[tuple, dict] = {}
    for code, field, row, instrument, element, message in gaps:
        key = ("ERROR", f"FUNDSXML/{code}", field)
        g = groups.setdefault(
            key,
            {
                "sev": "ERROR",
                "level": "portfolio" if code == "SHARES" else "position",
                "raw": 0,
                "items": {},
                "message": message or f"FundsXML: {element}",
            },
        )
        g["raw"] += 1
        dkey = "Portfolio" if code == "SHARES" else (instrument or f"Zeile {row}")
        g["items"].setdefault(dkey, [element, row, {""}, ""])
    return groups


def _measures(files: list[dict], rules: dict) -> list[dict]:
    """The single fixes with the widest effect: per direction, supplier and field."""
    agg: dict[tuple, dict] = {}
    for f in files:
        for r in f.get("rules", []):
            if r["sev"] != "ERROR":
                continue
            target = r["field"] or r["rule"]
            key = (f["kind"], f["supplier"], target)
            m = agg.setdefault(
                key,
                {
                    "kind": f["kind"],
                    "supplier": f["supplier"],
                    "field": r["field"],
                    "rules": set(),
                    "files": set(),
                    "distinct": 0,
                },
            )
            m["rules"].add(r["rule"])
            m["files"].add(f["rel"])
            m["distinct"] += r["distinct"]
    out = []
    for m in agg.values():
        m["rules"] = sorted(m["rules"])
        m["files"] = len(m["files"])
        out.append(m)
    return sorted(out, key=lambda m: (-m["files"], -m["distinct"]))[:200]


def _roundtrip_summary() -> dict:
    path = TESTFILES / "tpt_roundtrip" / "report.json"
    if not path.exists():
        return {}
    s = json.loads(path.read_text())["summary"]
    return {
        "files": s.get("files"),
        "rows": s.get("rows"),
        "losslessBlock": s.get("block", {}).get("lossless"),
        "losslessCore": s.get("core", {}).get("lossless"),
        "structureProblems": len(s.get("core", {}).get("structureProblems", {})),
        "validated": s.get("validation", {}).get("validated"),
        "newRules": len(s.get("validation", {}).get("rulesOnlyInRoundtrip", {})),
    }


if __name__ == "__main__":
    main()
