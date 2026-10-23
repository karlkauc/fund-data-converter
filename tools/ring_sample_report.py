"""A ring test over a few files per format, with an HTML report of the fields each round trip loses.

From TPT, openfunds and FundsXML as start format, each start file makes two full trips through all
three formats and two two-format reference trips::

    tpt:       tpt>of>fx>tpt   tpt>fx>of>tpt   ref tpt>fx>tpt   ref tpt>of>tpt
    openfunds: of>fx>tpt>of    of>tpt>fx>of    ref of>fx>of     ref of>tpt>of
    fundsxml:  fx>tpt>of>fx    fx>of>tpt>fx    ref fx>tpt>fx    ref fx>of>fx

The references tell on which leg a field gets lost. Every step goes through ``app.service.convert``
with an explicit direction, like the web app; the intermediate files stay in ``<out>/<file>/``.

Compared with the source: TPT field by field per row, openfunds field by field per share class and
holding, FundsXML leaf by leaf by path pattern (as in ``batch_triangle_roundtrip.py``).

Usage: python tools/ring_sample_report.py [--files N] [--seed S] [--out DIR] [--workers N]
"""

# ruff: noqa: E501 – the page's CSS and JavaScript are kept as written

from __future__ import annotations

import argparse
import io
import json
import random
import re
import sys
import time
import traceback
import zipfile
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tools"))

from app.ingest.fundsxml_reader import parse_fundsxml  # noqa: E402
from app.ingest.openfunds_reader import looks_like_openfunds, read_openfunds  # noqa: E402
from app.ingest.tpt_reader import read_tpt  # noqa: E402
from app.service import Request, convert  # noqa: E402
from app.spec.catalog import load_catalog  # noqa: E402
from app.spec.openfunds import load_openfunds  # noqa: E402
from batch_openfunds_roundtrip import SAME_DATE, _by_key, _holding_key, _sc_key  # noqa: E402
from batch_tpt_roundtrip import _compare, _same  # noqa: E402
from batch_triangle_roundtrip import _leaves, _nav_fundsxml, _nav_tpt, _where  # noqa: E402

TRIPS = {
    "tpt": {
        "tpt>of>fx>tpt": ["openfunds", "fundsxml", "tpt"],
        "tpt>fx>of>tpt": ["fundsxml", "openfunds", "tpt"],
        "ref:tpt>fx>tpt": ["fundsxml", "tpt"],
        "ref:tpt>of>tpt": ["openfunds", "tpt"],
    },
    "openfunds": {
        "of>fx>tpt>of": ["fundsxml", "tpt", "openfunds"],
        "of>tpt>fx>of": ["tpt", "fundsxml", "openfunds"],
        "ref:of>fx>of": ["fundsxml", "openfunds"],
        "ref:of>tpt>of": ["tpt", "openfunds"],
    },
    "fundsxml": {
        "fx>tpt>of>fx": ["tpt", "openfunds", "fundsxml"],
        "fx>of>tpt>fx": ["openfunds", "tpt", "fundsxml"],
        "ref:fx>tpt>fx": ["tpt", "fundsxml"],
        "ref:fx>of>fx": ["openfunds", "fundsxml"],
    },
}
SHORT = {"tpt": "tpt", "fundsxml": "fx", "openfunds": "of"}
LABEL = {"tpt": "TPT", "fundsxml": "FundsXML", "openfunds": "openfunds"}
# Which leg a reference trip covers.
LEG = {
    "ref:tpt>fx>tpt": "TPT⇄FundsXML",
    "ref:tpt>of>tpt": "TPT⇄openfunds",
    "ref:of>fx>of": "openfunds⇄FundsXML",
    "ref:of>tpt>of": "openfunds⇄TPT",
    "ref:fx>tpt>fx": "FundsXML⇄TPT",
    "ref:fx>of>fx": "FundsXML⇄openfunds",
}
SAMPLES = 6  # example values per field and trip
MAX_POSITIONS = 10_000


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--files", type=int, default=10, help="start files per format")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default=str(ROOT / "testfiles" / "ring_sample"))
    ap.add_argument("--workers", type=int, default=2)
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    picked = _pick(args.files, args.seed)
    jobs = [(kind, path, origin) for kind, items in picked.items() for path, origin in items]
    print(f"{len(jobs)} start files", file=sys.stderr, flush=True)
    started = time.time()
    results: dict[str, dict] = {}
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        tasks = [pool.submit(_check_file, kind, path, origin, out) for kind, path, origin in jobs]
        for task in as_completed(tasks):
            rel, entry = task.result()
            results[rel] = entry
            print(
                f"[{len(results)}/{len(jobs)}] {rel}  {time.time() - started:.0f}s",
                file=sys.stderr,
                flush=True,
            )
    data = {
        "generated": time.strftime("%Y-%m-%d %H:%M"),
        "seed": args.seed,
        "elapsedSeconds": round(time.time() - started),
        "trips": {k: list(v) for k, v in TRIPS.items()},
        "legs": LEG,
        "files": dict(sorted(results.items())),
        "fields": _field_matrix(results),
    }
    (out / "report.json").write_text(json.dumps(data, indent=1, ensure_ascii=False, default=str))
    (out / "report.html").write_text(_html(data, out))
    print(f"report: {out / 'report.html'}", file=sys.stderr)


# -- picking the start files --------------------------------------------------------


def _usable(p: Path) -> bool:
    return (
        p.is_file()
        and ".DAV" not in p.parts
        and not any(part.startswith("backup_") for part in p.parts)
        and not p.name.upper().endswith("_REPLY.XML")
    )


def _spread(paths: list[Path], n: int, rng: random.Random) -> list[Path]:
    """``n`` paths spread over the size range: one from each of ``n`` equal slices, sorted by size."""
    paths = sorted(paths, key=lambda p: p.stat().st_size)
    if n <= 0:
        return []
    if len(paths) <= n:
        return paths
    step = len(paths) / n
    return [paths[int(i * step) + rng.randrange(max(1, int(step)))] for i in range(n)]


def _positions_ok(kind: str, path: Path) -> bool:
    data = path.read_bytes()
    if kind == "fundsxml":
        return b"<FundsXML4" in data[:4096] and data.count(b"<Position>") <= MAX_POSITIONS * 4
    return len(read_tpt(data, path.name).rows) <= MAX_POSITIONS


def _pick_kind(kind: str, cands: list[Path], n: int, rng: random.Random) -> list[Path]:
    """One file per size slice; a file over the position limit gives way to its smaller neighbour."""
    if n <= 0 or not cands:
        return []
    ordered = sorted(cands, key=lambda p: p.stat().st_size)
    chosen: list[Path] = []
    for p in _spread(ordered, n, rng):
        i = ordered.index(p)
        while i >= 0 and (ordered[i] in chosen or not _positions_ok(kind, ordered[i])):
            i -= 1
        if i >= 0:
            chosen.append(ordered[i])
    return chosen


def _pick(n: int, seed: int) -> dict[str, list[tuple[Path, str]]]:
    rng = random.Random(seed)
    tf = ROOT / "testfiles"
    tpt = [p for p in sorted((tf / "tpt").rglob("*")) if _usable(p) and p.suffix.lower() in (".xlsx", ".csv")]
    v8 = [p for p in tpt if "TPTV8" in p.name.upper()]
    picked_tpt = v8[:1] + _pick_kind("tpt", [p for p in tpt if p not in v8], n - len(v8[:1]), rng)

    fx = [p for p in sorted((tf / "fundsxml").rglob("*.xml")) if _usable(p)]
    top = [p for p in fx if p.parent == tf / "fundsxml"]
    picked_fx = _pick_kind("fundsxml", top, min(2, n), rng)
    picked_fx += _pick_kind("fundsxml", [p for p in fx if p not in top], n - len(picked_fx), rng)

    of: list[tuple[Path, str]] = []
    real = tf / "openfunds"
    if real.exists():
        of += [(p, "echt") for p in sorted(real.rglob("*")) if _usable(p) and _is_of(p)][:n]
    samples = ROOT / "backend" / "app" / "samples"
    of += [(p, "Beispiel") for p in sorted(samples.glob("openfunds_*")) if _is_of(p)][: max(0, n - len(of))]
    used = {p.stem for p in picked_tpt + picked_fx}
    gen = tf / "openfunds_generated"
    pools = {
        prefix: [
            p
            for p in sorted(gen.glob(f"{prefix}__*_openfunds.xlsx"))
            if p.name[len(prefix) + 2 : -len("_openfunds.xlsx")] not in used
        ]
        for prefix in ("tpt", "fx")
    }
    rest = n - len(of)
    for prefix, origin, count in (
        ("tpt", "aus TPT erzeugt", (rest + 1) // 2),
        ("fx", "aus FundsXML erzeugt", rest // 2),
    ):
        of += [(p, origin) for p in _spread(pools[prefix], count, rng)]
    return {
        "tpt": [(p, "echt") for p in picked_tpt],
        "openfunds": of[:n],
        "fundsxml": [(p, "echt") for p in picked_fx],
    }


def _is_of(p: Path) -> bool:
    return p.suffix.lower() in (".xlsx", ".csv", ".zip") and looks_like_openfunds(p.read_bytes(), p.name)


# -- running the trips --------------------------------------------------------------


def _rel(path: Path) -> str:
    return str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)


def _error_pattern(err: str) -> str:
    return re.sub(r"\[\d+\]", "", err)[:220]


def _step(data: bytes, filename: str, source: str, target: str) -> tuple[bytes, str, dict]:
    report, res = convert(Request(data, filename, direction=f"{source}-to-{target}", preview=False))
    body, name = res.data, res.filename
    if res.zipped:
        with zipfile.ZipFile(io.BytesIO(body)) as z:
            name = z.namelist()[0]
            body = z.read(name)
    info: dict = {
        "step": f"{SHORT[source]}>{SHORT[target]}",
        "issues": dict(Counter(f"{i['level']}:{i['code']}" for i in report["issues"])),
        "dataLoss": report.get("dataLoss"),
    }
    validation = report.get("validation")
    if validation:
        info["valid"] = validation.get("valid")
        info["schemaErrors"] = dict(Counter(_error_pattern(e) for e in validation.get("errors") or []))
    return body, name, info


def _read(kind: str, data: bytes, name: str):
    if kind == "tpt":
        return read_tpt(data, name)
    if kind == "openfunds":
        return read_openfunds(data, name)
    return parse_fundsxml(data)


def _check_file(kind: str, path: Path, origin: str, out: Path) -> tuple[str, dict]:
    rel = _rel(path)
    work = out / re.sub(r"[^\w.-]+", "_", path.stem)
    work.mkdir(parents=True, exist_ok=True)
    data = path.read_bytes()
    entry: dict = {"kind": kind, "origin": origin, "work": work.name, "trips": {}}
    try:
        src = _read(kind, data, path.name)
        entry.update(_size(kind, src))
        entry["nav"] = _nav(kind, src)
    except Exception as exc:  # noqa: BLE001 – report and carry on
        entry["error"] = f"read: {type(exc).__name__}: {exc}"
        return rel, entry
    for trip, chain in TRIPS[kind].items():
        res: dict = {"steps": []}
        entry["trips"][trip] = res
        cur, fname, fmt = data, path.name, kind
        try:
            for target in chain:
                cur, fname, info = _step(cur, fname, fmt, target)
                res["steps"].append(info)
                prefix = trip.replace("ref:", "ref_").replace(">", "-")
                (work / f"{prefix}__{len(res['steps'])}_{fname}").write_bytes(cur)
                fmt = target
            back = _read(kind, cur, fname)
            res["fields"] = _diff(kind, src, back)
            res["nav"] = _nav(kind, back)
        except Exception as exc:  # noqa: BLE001
            res["error"] = f"{type(exc).__name__}: {exc}"
            res["trace"] = traceback.format_exc(limit=6)
    return rel, entry


def _size(kind: str, src) -> dict:
    if kind == "tpt":
        return {"version": src.version, "rows": len(src.rows)}
    if kind == "openfunds":
        return {"shareclasses": len(src.shareclasses), "holdings": len(src.holdings)}
    return {"positions": sum(1 for _ in src.iter("Position"))}


def _nav(kind: str, doc) -> dict | None:
    """Portfolios per verdict: does the sum of the positions match the net assets?"""
    if kind == "tpt":
        checks = _nav_tpt([r.values for r in doc.rows])
    elif kind == "fundsxml":
        checks = _nav_fundsxml(doc)
    else:
        return None
    return dict(Counter(c["result"] for c in checks))


# -- comparing with the source ------------------------------------------------------


class _Fields:
    """Per field: values lost (empty after the trip), changed, added; a few examples."""

    def __init__(self) -> None:
        self.data: dict[str, dict] = {}

    def add(self, field: str, what: str, example: str | None = None) -> None:
        f = self.data.setdefault(field, {"lost": 0, "changed": 0, "added": 0, "examples": []})
        f[what] += 1
        if example is not None and what != "added" and len(f["examples"]) < SAMPLES:
            f["examples"].append(example)


def _diff(kind: str, src, back) -> dict[str, dict]:
    fields = _Fields()
    if kind == "tpt":
        diffs, added = _compare(src, [r.values for r in back.rows])
        for row, field, a, b in diffs:
            if row is None:
                fields.add("(Zeilenzahl)", "changed", f"{a} → {b}")
                continue
            fields.add(
                field,
                "lost" if not b else "changed",
                f"Zeile {row}: {a} → {b or '(leer)'}",
            )
        for field, count in added.items():
            for _ in range(count):
                fields.add(field, "added")
    elif kind == "openfunds":
        for part, records, key in (
            ("Anteilsklasse", (src.shareclasses, back.shareclasses), _sc_key),
            ("Position", (src.holdings, back.holdings), _holding_key),
        ):
            orig, got_all = _by_key(records[0], key), _by_key(records[1], key)
            for k, values in orig.items():
                got = got_all.get(k)
                if got is None:
                    fields.add(f"({part} fehlt)", "lost", k)
                    continue
                if part == "Anteilsklasse":
                    for nos, aum in SAME_DATE:
                        if nos in values and nos not in got and aum in got:
                            got = got | {nos: got[aum]}
                for field, value in values.items():
                    if field not in got:
                        fields.add(field, "lost", f"{k}: {value} → (leer)")
                    elif not _same(value, got[field]):
                        fields.add(field, "changed", f"{k}: {value} → {got[field]}")
                for field in got.keys() - values.keys():
                    fields.add(field, "added")
            for k in got_all.keys() - orig.keys():
                fields.add(f"({part} neu)", "added", k)
    else:
        owners: dict = {}
        orig = _leaves(src, owners)
        got = _leaves(back)
        got_paths = dict(got)
        lost_paths = set()
        for item in sorted(orig - got):
            path, value = item
            lost_paths.add(path)
            pattern = _where(item, owners)
            if path in got_paths:
                fields.add(pattern, "changed", f"{path}: {value} → {got_paths[path]}")
            else:
                fields.add(pattern, "lost", f"{path} = {value}")
        for path, _value in got - orig:
            if path not in lost_paths:
                fields.add(_where((path, _value), owners), "added")
    return fields.data


# -- the field matrix ---------------------------------------------------------------


def _field_names() -> dict[str, str]:
    names: dict[str, str] = {}
    for version in ("V7", "V8"):
        try:
            catalog = load_catalog(version)
        except Exception:  # noqa: BLE001, S112 – a version without catalog
            continue
        for key, f in catalog.by_key.items():
            names.setdefault(f"tpt:{key}", f.num_data.replace("_", " "))
    for of_id, f in load_openfunds().by_id.items():
        names[f"of:{of_id}"] = f.name
    return names


def _field_matrix(results: dict[str, dict]) -> dict[str, list[dict]]:
    """Per start format: one row per field with, per trip, lost/changed/added and the files."""
    names = _field_names()
    out: dict[str, list[dict]] = {}
    for kind, trips in TRIPS.items():
        rows: dict[str, dict] = {}
        for rel, entry in results.items():
            if entry["kind"] != kind:
                continue
            for trip in trips:
                for field, f in entry["trips"].get(trip, {}).get("fields", {}).items():
                    row = rows.setdefault(field, {"field": field, "trips": {}})
                    cell = row["trips"].setdefault(
                        trip,
                        {
                            "lost": 0,
                            "changed": 0,
                            "added": 0,
                            "files": 0,
                            "examples": [],
                        },
                    )
                    for k in ("lost", "changed", "added"):
                        cell[k] += f[k]
                    if f["lost"] or f["changed"]:
                        cell["files"] += 1
                    cell["examples"] += [f"{Path(rel).name}: {e}" for e in f["examples"][:3]]
        for row in rows.values():
            prefix = {"tpt": "tpt", "openfunds": "of"}.get(kind)
            row["name"] = names.get(f"{prefix}:{row['field']}", "") if prefix else ""
            for cell in row["trips"].values():
                cell["examples"] = cell["examples"][:10]
        out[kind] = sorted(
            rows.values(),
            key=lambda r: -sum(c["lost"] + c["changed"] for c in r["trips"].values()),
        )
    return out


# -- HTML ---------------------------------------------------------------------------

CSS = """
:root{--bg:#fff;--fg:#1d2330;--muted:#5d6675;--line:#dde1e8;--head:#f3f5f8;--ok:#1a7f37;--bad:#c62828;
--warn:#9a6700;--accent:#2457c5;--heat:198,40,40;--chg:154,103,0}
@media (prefers-color-scheme:dark){:root{--bg:#14171c;--fg:#e4e7ec;--muted:#98a1b0;--line:#2c323c;
--head:#1c2027;--ok:#4cc26a;--bad:#ff6b6b;--warn:#e3b341;--accent:#7aa2ff;--heat:255,107,107;--chg:227,179,65}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font:14px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
main{max-width:1400px;margin:0 auto;padding:24px 16px 64px}
h1{font-size:22px;margin:0 0 4px}h2{font-size:18px;margin:36px 0 8px}h3{font-size:15px;margin:20px 0 6px}
.muted{color:var(--muted)}.ok{color:var(--ok)}.bad{color:var(--bad)}.warn{color:var(--warn)}
table{border-collapse:collapse;width:100%;margin:8px 0}th,td{border:1px solid var(--line);padding:4px 8px;
text-align:left;vertical-align:top}th{background:var(--head);font-weight:600;position:sticky;top:0}
td.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.wrap{overflow-x:auto}.cell{cursor:pointer}.cell:hover{outline:2px solid var(--accent)}
.ex{font:12px/1.4 ui-monospace,Menlo,Consolas,monospace;white-space:pre-wrap;word-break:break-all;
background:var(--head);padding:6px 8px}.tabs{display:flex;gap:6px;flex-wrap:wrap;margin:12px 0}
.tabs button,.ctl button{border:1px solid var(--line);background:var(--head);color:var(--fg);
padding:6px 12px;border-radius:6px;cursor:pointer;font:inherit}
.tabs button[aria-pressed=true],.ctl button[aria-pressed=true]{background:var(--accent);color:#fff;border-color:var(--accent)}
.ctl{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:8px 0}
input[type=search]{padding:6px 8px;border:1px solid var(--line);border-radius:6px;background:var(--bg);
color:var(--fg);font:inherit;min-width:240px}code{font:12px ui-monospace,Menlo,Consolas,monospace}
.leg{font-size:12px;white-space:nowrap}a{color:var(--accent)}
"""

JS = r"""
const D = JSON.parse(document.getElementById('data').textContent);
const KINDS = ['tpt', 'openfunds', 'fundsxml'];
const LABEL = {tpt: 'TPT', openfunds: 'openfunds', fundsxml: 'FundsXML'};
const hasLoss = k => D.fields[k].some(r => Object.values(r.trips).some(c => c.lost || c.changed));
let kind = KINDS.find(hasLoss) || 'tpt', onlyLoss = true, query = '';
const esc = s => String(s).replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
function leg(row) {
  const refs = D.trips[kind].filter(t => t.startsWith('ref:'));
  const hit = refs.filter(t => { const c = row.trips[t]; return c && (c.lost || c.changed); });
  if (hit.length) return hit.map(t => D.legs[t]).join(', ');
  const full = D.trips[kind].filter(t => !t.startsWith('ref:'));
  return full.some(t => { const c = row.trips[t]; return c && (c.lost || c.changed); }) ? 'nur im vollen Umlauf' : '';
}
function render() {
  document.querySelectorAll('.tabs button').forEach(b => b.setAttribute('aria-pressed', b.dataset.kind === kind));
  document.querySelectorAll('[data-only]').forEach(b => b.setAttribute('aria-pressed', String(onlyLoss) === b.dataset.only));
  const trips = D.trips[kind];
  const rows = D.fields[kind].filter(r => {
    const bad = trips.some(t => r.trips[t] && (r.trips[t].lost || r.trips[t].changed));
    if (onlyLoss && !bad) return false;
    if (query && !(r.field + ' ' + r.name).toLowerCase().includes(query)) return false;
    return true;
  });
  const max = Math.max(1, ...D.fields[kind].flatMap(r => trips.map(t => r.trips[t] ? r.trips[t].files : 0)));
  let h = '<div class="wrap"><table><thead><tr><th>Feld</th><th>Strecke</th>' +
    trips.map(t => `<th>${esc(t.replace('ref:', 'Referenz '))}</th>`).join('') + '</tr></thead><tbody>';
  rows.forEach((r, i) => {
    h += `<tr><td><code>${esc(r.field)}</code>${r.name ? `<br><span class="muted">${esc(r.name)}</span>` : ''}</td>` +
      `<td class="leg">${esc(leg(r))}</td>`;
    trips.forEach(t => {
      const c = r.trips[t];
      if (!c || !(c.lost || c.changed || c.added)) { h += '<td class="n muted">–</td>'; return; }
      const a = (c.lost || c.changed) ? 0.12 + 0.6 * c.files / max : 0;
      const rgb = c.lost ? 'var(--heat)' : 'var(--chg)';
      const parts = [];
      if (c.lost) parts.push(`<span class="bad">${c.lost} verloren</span>`);
      if (c.changed) parts.push(`<span class="warn">${c.changed} geändert</span>`);
      if (c.added) parts.push(`<span class="muted">${c.added} ergänzt</span>`);
      const files = (c.lost || c.changed) ? `<br><span class="muted">${c.files} Datei(en)</span>` : '';
      h += `<td class="n cell" data-i="${i}" data-t="${esc(t)}" style="background:rgba(${rgb.replace('var(--heat)', getVar('--heat')).replace('var(--chg)', getVar('--chg'))},${a})">${parts.join('<br>')}${files}</td>`;
    });
    h += '</tr>';
  });
  h += '</tbody></table></div>';
  if (!rows.length) h = '<p class="muted">Keine Felder.</p>';
  const box = document.getElementById('matrix');
  box.innerHTML = `<p class="muted">${rows.length} von ${D.fields[kind].length} Feldern</p>` + h;
  box.querySelectorAll('.cell').forEach(td => td.addEventListener('click', () => {
    const next = td.parentElement.nextElementSibling;
    if (next && next.classList.contains('exrow') && next.dataset.t === td.dataset.t) { next.remove(); return; }
    if (next && next.classList.contains('exrow')) next.remove();
    const c = rows[+td.dataset.i].trips[td.dataset.t];
    const tr = document.createElement('tr');
    tr.className = 'exrow'; tr.dataset.t = td.dataset.t;
    tr.innerHTML = `<td colspan="${trips.length + 2}"><b>${esc(td.dataset.t)}</b><div class="ex">${
      c.examples.length ? c.examples.map(esc).join('\n') : 'keine Beispiele (nur ergänzt)'}</div></td>`;
    td.parentElement.after(tr);
  }));
}
function getVar(n) { return getComputedStyle(document.documentElement).getPropertyValue(n).trim(); }
document.querySelectorAll('.tabs button').forEach(b => b.addEventListener('click', () => { kind = b.dataset.kind; render(); }));
document.querySelectorAll('[data-only]').forEach(b => b.addEventListener('click', () => { onlyLoss = b.dataset.only === 'true'; render(); }));
document.getElementById('q').addEventListener('input', e => { query = e.target.value.toLowerCase(); render(); });
render();
"""


def _trip_totals(entry: dict, trip: str) -> tuple[int, int, int]:
    fields = entry["trips"].get(trip, {}).get("fields", {})
    return (
        sum(f["lost"] for f in fields.values()),
        sum(f["changed"] for f in fields.values()),
        sum(1 for f in fields.values() if f["lost"] or f["changed"]),
    )


def _nav_text(src: dict | None, back: dict | None) -> str:
    if src is None or back is None:
        return '<span class="muted">–</span>'
    worse = back.get("differs", 0) - src.get("differs", 0)
    if worse > 0:
        return f'<span class="bad">{worse} schlechter</span>'
    return '<span class="ok">ok</span>'


def _schema_text(steps: list[dict]) -> str:
    fx = [s for s in steps if "valid" in s]
    if not fx:
        return '<span class="muted">–</span>'
    bad = [s["step"] for s in fx if not s["valid"]]
    return (
        f'<span class="bad">ungültig ({", ".join(bad)})</span>' if bad else '<span class="ok">gültig</span>'
    )


def _overview(data: dict) -> str:
    rows = []
    for kind, trips in TRIPS.items():
        entries = [e for e in data["files"].values() if e["kind"] == kind]
        for trip in trips:
            done = [e for e in entries if "fields" in e["trips"].get(trip, {})]
            errors = sum(1 for e in entries if "error" in e or "error" in e["trips"].get(trip, {}))
            lossless = sum(1 for e in done if _trip_totals(e, trip)[2] == 0)
            invalid = sum(1 for e in done if any(s.get("valid") is False for s in e["trips"][trip]["steps"]))
            worse = sum(
                1
                for e in done
                if e.get("nav") is not None
                and e["trips"][trip].get("nav", {}).get("differs", 0) > e["nav"].get("differs", 0)
            )
            lost = sum(_trip_totals(e, trip)[0] for e in done)
            changed = sum(_trip_totals(e, trip)[1] for e in done)
            rows.append(
                f"<tr><td>{LABEL[kind]}</td><td><code>{escape(trip)}</code></td>"
                f'<td class="n">{len(entries)}</td><td class="n">{lossless}</td>'
                f'<td class="n">{lost:,}</td><td class="n">{changed:,}</td>'
                f'<td class="n{" bad" if invalid else ""}">{invalid}</td>'
                f'<td class="n{" bad" if worse else ""}">{worse}</td>'
                f'<td class="n{" bad" if errors else ""}">{errors}</td></tr>'
            )
    return (
        '<div class="wrap"><table><thead><tr><th>Start</th><th>Umlauf</th><th>Dateien</th>'
        "<th>verlustfrei</th><th>Werte verloren</th><th>Werte geändert</th><th>FundsXML ungültig</th>"
        "<th>Fondsvolumen schlechter</th><th>Fehler</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></div>"
    )


def _per_file(data: dict) -> str:
    parts = []
    for kind, trips in TRIPS.items():
        rows = []
        for rel, e in data["files"].items():
            if e["kind"] != kind:
                continue
            size = ", ".join(
                f"{k} {v}"
                for k, v in e.items()
                if k in ("version", "rows", "shareclasses", "holdings", "positions")
            )
            cells = []
            for trip in trips:
                t = e["trips"].get(trip, {})
                if "error" in e or "error" in t:
                    msg = e.get("error") or t.get("error", "")
                    cells.append(f'<td class="bad" title="{escape(msg)}">Fehler: {escape(msg[:90])}</td>')
                    continue
                lost, changed, nfields = _trip_totals(e, trip)
                text = (
                    '<span class="ok">verlustfrei</span>'
                    if nfields == 0
                    else f'<span class="bad">{lost:,} verloren</span> / <span class="warn">{changed:,} geändert</span>'
                    f'<br><span class="muted">{nfields} Felder</span>'
                )
                cells.append(
                    f"<td>{text}<br>Schema: {_schema_text(t['steps'])}"
                    f"<br>Volumen: {_nav_text(e.get('nav'), t.get('nav'))}</td>"
                )
            rows.append(
                f'<tr><td><a href="{escape(e["work"])}/">{escape(Path(rel).name)}</a>'
                f'<br><span class="muted">{escape(e["origin"])}; {escape(size)}</span></td>{"".join(cells)}</tr>'
            )
        head = "".join(f"<th>{escape(t.replace('ref:', 'Referenz '))}</th>" for t in trips)
        parts.append(
            f"<h3>Start {LABEL[kind]}</h3><div class='wrap'><table><thead><tr><th>Datei</th>{head}</tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table></div>"
        )
    return "".join(parts)


def _schema_errors(data: dict) -> str:
    counts: Counter = Counter()
    for e in data["files"].values():
        for t in e["trips"].values():
            for s in t.get("steps", []):
                for err in s.get("schemaErrors") or {}:
                    counts[(s["step"], err)] += 1
    if not counts:
        return "<p>Alle erzeugten FundsXML-Dateien sind schemagültig.</p>"
    rows = "".join(
        f'<tr><td><code>{escape(step)}</code></td><td class="n">{n}</td><td><code>{escape(err)}</code></td></tr>'
        for (step, err), n in counts.most_common(60)
    )
    return (
        '<p class="muted">Anzahl = Schritte (über alle Umläufe), in denen der Fehler vorkommt.</p>'
        '<div class="wrap"><table><thead><tr><th>Schritt</th><th>Anzahl</th><th>Fehler</th></tr></thead>'
        f"<tbody>{rows}</tbody></table></div>"
    )


def _html(data: dict, out: Path) -> str:
    payload = json.dumps({k: data[k] for k in ("trips", "legs", "fields")}, ensure_ascii=False)
    payload = payload.replace("</", "<\\/")
    tabs = "".join(
        f'<button type="button" data-kind="{k}">Start {LABEL[k]} ({len(data["fields"][k])} Felder)</button>'
        for k in TRIPS
    )
    return f"""<!doctype html>
<html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Ringtest Feldverluste</title><style>{CSS}</style></head><body><main>
<h1>Ringtest: welche Felder welcher Umlauf verliert</h1>
<p class="muted">Erzeugt {escape(data["generated"])}, Seed {data["seed"]}, Laufzeit {data["elapsedSeconds"]} s.
Je Startformat bis zu {max(Counter(e["kind"] for e in data["files"].values()).values(), default=0)} Dateien,
zwei volle Umläufe über alle drei Formate und zwei Referenzen über zwei Formate.
<b>verloren</b> = in der Quelle gefüllt, danach leer; <b>geändert</b> = anderer Wert; <b>ergänzt</b> = in
der Quelle leer, danach gefüllt (kein Verlust).</p>
<h2>Übersicht</h2>{_overview(data)}
<h2>Felder je Umlauf</h2>
<p class="muted">Die Spalte <b>Strecke</b> nennt die Referenz, die das Feld ebenfalls verliert. „nur im vollen
Umlauf“ heißt: Erst die Kombination der drei Formate verliert es. Klick auf eine Zelle zeigt Beispiele
(Datei, Zeile oder Pfad, Wert vorher → nachher). FundsXML-Felder sind Pfadmuster ohne Schlüssel.</p>
<div class="tabs">{tabs}</div>
<div class="ctl"><button type="button" data-only="true">nur Verluste/Änderungen</button>
<button type="button" data-only="false">alle Felder</button>
<input type="search" id="q" placeholder="Feld suchen (Nummer, OF-ID, Pfad, Name)"></div>
<div id="matrix"></div>
<h2>Je Datei</h2>{_per_file(data)}
<h2>Schemafehler im erzeugten FundsXML</h2>{_schema_errors(data)}
<script type="application/json" id="data">{payload}</script>
<script>{JS}</script>
</main></body></html>
"""


if __name__ == "__main__":
    main()
