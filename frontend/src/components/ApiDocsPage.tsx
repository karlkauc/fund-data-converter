import clsx from "clsx";
import { useState, type ReactNode } from "react";
import { ISSUE_CODES, issueText, useI18n, type Lang } from "../lib/i18n";

// Keep in sync with backend/app/api/convert.py (options, headers) and app/config.py (limits).

type Row = [string, string];

const TEXT = {
  en: {
    title: "API",
    intro:
      "The converter can be used from scripts as well: one HTTP request uploads a file and returns the converted file together with a report. No account, no API key – the same limits as in the browser apply.",
    quick: "Quick start",
    endpoint: "Endpoint",
    endpointText:
      "Send the file as multipart/form-data in the field file. The source format follows from the content (TPT, FundsXML 4 or openfunds); target picks the output. Without target, TPT and openfunds become FundsXML 4 and FundsXML becomes TPT. All other fields are optional.",
    params: "Parameters",
    colName: "Field",
    colMeaning: "Meaning",
    modes: "Response modes",
    report: "Report fields",
    headers: "Headers with response=file",
    examples: "Examples",
    limits: "Limits",
    errors: "Errors",
    errorsText: 'Errors are JSON of the form {"detail": "…"}. A conversion with warnings or XSD errors is still a success (200); check validation.valid, issueCounts and dataLoss.',
    issues: "Issue codes",
    issuesText:
      "Each entry in issues has level (error, warning, info), code, an English message and, where it applies, field (TPT field number), row, path (FundsXML), value and params. The code is stable; the texts below are the ones the web interface shows.",
    openapi: "Machine-readable description (OpenAPI):",
    copy: "Copy",
    copied: "Copied",
    paramRows: [
      ["file", "required. TPT as .xlsx/.csv (V7 or V8), FundsXML 4 as .xml or openfunds as .xlsx/.csv/.zip (OF-ID columns)"],
      ["response", "json (default) · file · zip – see below"],
      ["target", "tpt · fundsxml · openfunds: the output format (default: FundsXML, for FundsXML input TPT). The upload's own format means the default"],
      ["direction", "auto (default) · tpt-to-fundsxml · fundsxml-to-tpt · openfunds-to-fundsxml · fundsxml-to-openfunds · tpt-to-openfunds · openfunds-to-tpt. Instead of target: if the file is another format, the request is refused with 422"],
      ["tpt_version", "V7 · V8. TPT input: overrides the detected version. FundsXML input: the TPT version to write (default: as found in the document)"],
      ["include_core", "TPT → FundsXML: write the core structures Fund, Position, AssetMasterData (default true)"],
      ["include_block", "TPT → FundsXML: write the Solvency II TPT block (default true). At least one of the two must be on"],
      ["data_supplier_name / _short / _country", "TPT → FundsXML: ControlData/DataSupplier. Default: TPT fields 117 and 122"],
      ["output_format", "TPT or openfunds output: xlsx (default) · csv. openfunds CSV with holdings comes as a zip of two CSV files"],
      ["delimiter", "CSV output: semicolon (default) · comma · pipe · tab"],
      ["all_columns", "TPT output: every TPT column (true, default) or only filled ones. openfunds output: every OFST/OFPH column (default false: only filled ones)"],
      ["of_header_names", "openfunds output: a second header row with the field names (default false)"],
      ["non_openfunds_columns", "TPT → openfunds: TPT fields without an openfunds column as columns TPT_<field> (default true; false drops them and reports hop_data_loss)"],
      ["implied_tpt_attributes", "openfunds → FundsXML: also keep TPT values the FundsXML implies as custom attributes TPT_<field> (default true; false leaves out those the reverse conversion derives exactly – a smaller file, nothing lost)"],
      ["preview", "response=json: include the table and XML previews of the web interface (default true; scripts usually send false)"],
    ] as Row[],
    modeRows: [
      ["json", "The report as JSON; the converted file is base64-encoded in output.base64."],
      ["file", "The converted file itself (Content-Disposition carries the file name). Key figures come as X-Conversion-* headers."],
      ["zip", "One zip with the converted file, report.json (the full report without base64) and issues.csv (semicolon-separated, UTF-8 with BOM for Excel)."],
    ] as Row[],
    reportRows: [
      ["direction", "tpt-to-fundsxml · fundsxml-to-tpt · openfunds-to-fundsxml · fundsxml-to-openfunds · tpt-to-openfunds · openfunds-to-tpt"],
      ["input", "file name, kind (tpt, fundsxml, openfunds), detected format, delimiter, version (TPT: and how it was found; openfunds: layout flat/narrow), columns, columns that are not TPT/openfunds fields, outputVersion"],
      ["summary", "portfolios or funds/shareclasses, positions, assets, custom attributes, portfolioList (id, date, name, currency, NAV, positions)"],
      ["coverage", "per field present: written to the TPT block, the core structures or as custom attribute"],
      ["validation", "output FundsXML: valid and the XSD errors of the generated document; null for TPT and openfunds output"],
      ["issues / issueCounts", "messages (see issue codes) and their number per level"],
      ["dataLoss", "lost (values not in the output), keptAsCustomAttribute, notInCoreStructures (only in the TPT block), codes. Counted in full even where issues lists only the first 25 per code. TPT ⇄ openfunds: fields the other format has no place for (hop_data_loss). null for FundsXML input"],
      ["output", "filename, mimeType, size, zipped (above 8 MB the file is delivered zipped), sha256 (and base64 with response=json)"],
      ["meta", "converterVersion, fundsxmlSchema, input bytes and sha256, durationMs"],
      ["rateLimit", "your rate limit after this conversion: per window (minute, hour) limit, remaining and resetSeconds"],
    ] as Row[],
    headerRows: [
      ["X-Conversion-Direction", "tpt-to-fundsxml · fundsxml-to-tpt · openfunds-to-fundsxml · fundsxml-to-openfunds · tpt-to-openfunds · openfunds-to-tpt"],
      ["X-Conversion-Valid", "true · false · empty (TPT or openfunds output, nothing to validate)"],
      ["X-Conversion-Portfolios / -Positions", "counts"],
      ["X-Conversion-Errors / -Warnings / -Infos", "messages per level"],
      ["X-Conversion-Data-Lost", "number of values not in the output; empty for FundsXML input"],
      ["X-Conversion-Issue-Codes", "comma-separated codes"],
      ["X-Conversion-Report", "the report without the per-row lists (issues, portfolioList, coverage.fields), as base64url JSON"],
      ["X-RateLimit-Limit-Minute / -Remaining-Minute / -Reset-Minute", "your rate limit (also -Hour); Reset in seconds, 0 while the window has not started. On every /api/convert response, 429 included"],
    ] as Row[],
    limitRows: [
      ["Upload", "25 MB per file"],
      ["Positions", "10,000 per file – split larger files by portfolio"],
      ["Rate", "20 conversions per minute and 200 per hour per IP address; then 429 with Retry-After. GET /api/limits shows what is left without using a conversion"],
      ["Output", "files above 8 MB are delivered zipped"],
    ] as Row[],
    errorRows: [
      ["400", "invalid option, empty file"],
      ["413", "file above the upload limit"],
      ["422", "the file cannot be converted (not TPT/FundsXML/openfunds, unreadable, too many positions, direction mismatch)"],
      ["429", "rate limit exceeded – wait for Retry-After seconds"],
      ["500", "internal error – please report it via Feedback"],
    ] as Row[],
  },
  de: {
    title: "API",
    intro:
      "Der Konverter lässt sich auch aus Skripten ansteuern: Ein HTTP-Request lädt eine Datei hoch und liefert die konvertierte Datei samt Report zurück. Kein Account, kein API-Key – es gelten dieselben Limits wie im Browser.",
    quick: "Schnellstart",
    endpoint: "Endpoint",
    endpointText:
      "Die Datei wird als multipart/form-data im Feld file gesendet. Das Quellformat ergibt sich aus dem Inhalt (TPT, FundsXML 4 oder openfunds); target wählt die Ausgabe. Ohne target wird aus TPT und openfunds FundsXML 4, aus FundsXML TPT. Alle anderen Felder sind optional.",
    params: "Parameter",
    colName: "Feld",
    colMeaning: "Bedeutung",
    modes: "Antwortformate",
    report: "Report-Felder",
    headers: "Header bei response=file",
    examples: "Beispiele",
    limits: "Limits",
    errors: "Fehler",
    errorsText: 'Fehler kommen als JSON der Form {"detail": "…"}. Eine Konvertierung mit Warnungen oder XSD-Fehlern ist trotzdem erfolgreich (200); entscheidend sind validation.valid, issueCounts und dataLoss.',
    issues: "Issue-Codes",
    issuesText:
      "Jeder Eintrag in issues hat level (error, warning, info), code, eine englische message und, wo zutreffend, field (TPT-Feldnummer), row, path (FundsXML), value und params. Der Code ist stabil; die Texte unten sind die der Weboberfläche.",
    openapi: "Maschinenlesbare Beschreibung (OpenAPI):",
    copy: "Kopieren",
    copied: "Kopiert",
    paramRows: [
      ["file", "Pflicht. TPT als .xlsx/.csv (V7 oder V8), FundsXML 4 als .xml oder openfunds als .xlsx/.csv/.zip (OF-ID-Spalten)"],
      ["response", "json (Standard) · file · zip – siehe unten"],
      ["target", "tpt · fundsxml · openfunds: das Ausgabeformat (Standard: FundsXML, bei FundsXML-Eingabe TPT). Das eigene Format der Datei bedeutet den Standard"],
      ["direction", "auto (Standard) · tpt-to-fundsxml · fundsxml-to-tpt · openfunds-to-fundsxml · fundsxml-to-openfunds · tpt-to-openfunds · openfunds-to-tpt. Statt target: Ist die Datei in einem anderen Format, wird mit 422 abgelehnt"],
      ["tpt_version", "V7 · V8. TPT-Eingabe: überschreibt die erkannte Version. FundsXML-Eingabe: die zu schreibende TPT-Version (Standard: wie im Dokument)"],
      ["include_core", "TPT → FundsXML: Core-Strukturen Fund, Position, AssetMasterData schreiben (Standard true)"],
      ["include_block", "TPT → FundsXML: Solvency-II-TPT-Block schreiben (Standard true). Mindestens eines der beiden muss aktiv sein"],
      ["data_supplier_name / _short / _country", "TPT → FundsXML: ControlData/DataSupplier. Standard: TPT-Felder 117 und 122"],
      ["output_format", "TPT- oder openfunds-Ausgabe: xlsx (Standard) · csv. openfunds-CSV mit Holdings kommt als ZIP mit zwei CSV-Dateien"],
      ["delimiter", "CSV-Ausgabe: semicolon (Standard) · comma · pipe · tab"],
      ["all_columns", "TPT-Ausgabe: alle TPT-Spalten (true, Standard) oder nur befüllte. openfunds-Ausgabe: alle OFST/OFPH-Spalten (Standard false: nur befüllte)"],
      ["of_header_names", "openfunds-Ausgabe: zweite Kopfzeile mit den Feldnamen (Standard false)"],
      ["non_openfunds_columns", "TPT → openfunds: TPT-Felder ohne openfunds-Spalte als Spalten TPT_<Feld> (Standard true; false lässt sie weg und meldet hop_data_loss)"],
      ["implied_tpt_attributes", "openfunds → FundsXML: TPT-Werte, die das FundsXML schon enthält, zusätzlich als Custom Attributes TPT_<Feld> (Standard true; false lässt die weg, die die Rückumwandlung exakt ableitet – kleinere Datei, kein Verlust)"],
      ["preview", "response=json: Tabellen- und XML-Vorschau der Weboberfläche mitliefern (Standard true; Skripte senden meist false)"],
    ] as Row[],
    modeRows: [
      ["json", "Der Report als JSON; die konvertierte Datei steckt base64-kodiert in output.base64."],
      ["file", "Die konvertierte Datei selbst (Dateiname im Content-Disposition-Header). Kennzahlen als X-Conversion-*-Header."],
      ["zip", "Ein ZIP mit der konvertierten Datei, report.json (der volle Report ohne base64) und issues.csv (Semikolon-getrennt, UTF-8 mit BOM für Excel)."],
    ] as Row[],
    reportRows: [
      ["direction", "tpt-to-fundsxml · fundsxml-to-tpt · openfunds-to-fundsxml · fundsxml-to-openfunds · tpt-to-openfunds · openfunds-to-tpt"],
      ["input", "Dateiname, kind (tpt, fundsxml, openfunds), erkanntes Format, Trennzeichen, Version (TPT: und woher sie stammt; openfunds: Layout flat/narrow), Spalten, Spalten ohne TPT-/openfunds-Feld, outputVersion"],
      ["summary", "Portfolios bzw. Fonds/Anteilsklassen, Positionen, Assets, CustomAttributes, portfolioList (ID, Datum, Name, Währung, NAV, Positionen)"],
      ["coverage", "je vorhandenem Feld: in TPT-Block, Core-Strukturen oder als CustomAttribute geschrieben"],
      ["validation", "FundsXML-Ausgabe: valid und die XSD-Fehler des erzeugten Dokuments; null bei TPT- und openfunds-Ausgabe"],
      ["issues / issueCounts", "Hinweise (siehe Issue-Codes) und ihre Anzahl je Level"],
      ["dataLoss", "lost (Werte nicht im Ergebnis), keptAsCustomAttribute, notInCoreStructures (nur im TPT-Block), codes. Vollständig gezählt, auch wenn issues je Code nur die ersten 25 auflistet. TPT ⇄ openfunds: Felder, für die das andere Format keinen Platz hat (hop_data_loss). null bei FundsXML-Eingabe"],
      ["output", "filename, mimeType, size, zipped (über 8 MB wird gezippt geliefert), sha256 (und base64 bei response=json)"],
      ["meta", "converterVersion, fundsxmlSchema, Bytes und sha256 der Eingabe, durationMs"],
      ["rateLimit", "dein Rate-Limit nach dieser Konvertierung: je Zeitfenster (minute, hour) limit, remaining und resetSeconds"],
    ] as Row[],
    headerRows: [
      ["X-Conversion-Direction", "tpt-to-fundsxml · fundsxml-to-tpt · openfunds-to-fundsxml · fundsxml-to-openfunds · tpt-to-openfunds · openfunds-to-tpt"],
      ["X-Conversion-Valid", "true · false · leer (TPT- oder openfunds-Ausgabe, nichts zu validieren)"],
      ["X-Conversion-Portfolios / -Positions", "Anzahlen"],
      ["X-Conversion-Errors / -Warnings / -Infos", "Hinweise je Level"],
      ["X-Conversion-Data-Lost", "Anzahl der Werte, die nicht im Ergebnis sind; leer bei FundsXML-Eingabe"],
      ["X-Conversion-Issue-Codes", "Codes, kommagetrennt"],
      ["X-Conversion-Report", "der Report ohne zeilenweise Listen (issues, portfolioList, coverage.fields), als base64url-JSON"],
      ["X-RateLimit-Limit-Minute / -Remaining-Minute / -Reset-Minute", "dein Rate-Limit (ebenso -Hour); Reset in Sekunden, 0 solange das Zeitfenster nicht begonnen hat. Bei jeder Antwort von /api/convert, auch bei 429"],
    ] as Row[],
    limitRows: [
      ["Upload", "25 MB je Datei"],
      ["Positionen", "10.000 je Datei – größere Dateien nach Portfolio aufteilen"],
      ["Rate", "20 Konvertierungen pro Minute und 200 pro Stunde je IP-Adresse; danach 429 mit Retry-After. GET /api/limits zeigt den Rest, ohne eine Konvertierung zu verbrauchen"],
      ["Ausgabe", "Dateien über 8 MB werden gezippt geliefert"],
    ] as Row[],
    errorRows: [
      ["400", "ungültige Option, leere Datei"],
      ["413", "Datei über dem Upload-Limit"],
      ["422", "Datei nicht konvertierbar (kein TPT/FundsXML/openfunds, nicht lesbar, zu viele Positionen, falsche Richtung)"],
      ["429", "Rate-Limit überschritten – Retry-After Sekunden warten"],
      ["500", "interner Fehler – bitte über Feedback melden"],
    ] as Row[],
  },
} satisfies Record<Lang, unknown>;

function examples(api: string): Record<"curl" | "PowerShell" | "Python", string> {
  return {
    curl: `# TPT → FundsXML: save the XML, show the X-Conversion-* headers
curl -sS --fail-with-body -F file=@fund.xlsx -F response=file -OJ -D - ${api}

# Report only, without previews
curl -sS -F file=@fund.xlsx -F preview=false ${api} \\
  | jq '{valid: .validation.valid, issues: .issueCounts, dataLoss: .dataLoss}'

# FundsXML → TPT V8 as CSV; converted file, report.json and issues.csv in one zip
curl -sS --fail-with-body -F file=@fundsxml.xml -F tpt_version=V8 \\
  -F output_format=csv -F response=zip -OJ ${api}

# TPT → openfunds (share classes and holdings as XLSX)
curl -sS --fail-with-body -F file=@fund.xlsx -F target=openfunds -F response=file -OJ ${api}`,
    PowerShell: `# PowerShell 7+
$api = "${api}"

# Converted file plus key figures from the headers
$r = Invoke-WebRequest -Uri $api -Method Post -OutFile fund_FundsXML.xml -PassThru -Form @{
  file = Get-Item .\\fund.xlsx; response = "file"
}
"valid: $($r.Headers['X-Conversion-Valid']) · lost: $($r.Headers['X-Conversion-Data-Lost'])"

# JSON report, file decoded from base64
$rep = Invoke-RestMethod -Uri $api -Method Post -Form @{
  file = Get-Item .\\fundsxml.xml; output_format = "xlsx"; preview = "false"
}
[IO.File]::WriteAllBytes($rep.output.filename, [Convert]::FromBase64String($rep.output.base64))
$rep.issues | Where-Object level -ne "info" | Format-Table level, code, field, row, message`,
    Python: `import base64
import requests

API = "${api}"

with open("fund.xlsx", "rb") as f:
    r = requests.post(API, files={"file": f}, data={"preview": "false"}, timeout=120)
r.raise_for_status()  # 4xx: r.json()["detail"]
report = r.json()

with open(report["output"]["filename"], "wb") as out:
    out.write(base64.b64decode(report["output"]["base64"]))

print("valid:", report["validation"]["valid"], "| issues:", report["issueCounts"])
if report["dataLoss"]["lost"]:
    print("values lost:", report["dataLoss"])
for issue in report["issues"]:
    if issue["level"] != "info":
        print(issue["level"], issue["code"], issue.get("field", ""), issue["message"])`,
  };
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="mt-8">
      <h2 className="text-lg font-semibold tracking-tight">{title}</h2>
      <div className="mt-2 space-y-3 text-sm text-slate-700 dark:text-slate-300">{children}</div>
    </section>
  );
}

function Table({ head, rows }: { head?: [string, string]; rows: Row[] }) {
  return (
    <div className="panel overflow-x-auto">
      <table className="w-full text-sm">
        {head && (
          <thead className="hidden bg-slate-100 text-left sm:table-header-group text-xs uppercase tracking-wide text-slate-500 dark:bg-slate-800 dark:text-slate-400">
            <tr>
              <th className="px-3 py-2">{head[0]}</th>
              <th className="px-3 py-2">{head[1]}</th>
            </tr>
          </thead>
        )}
        <tbody>
          {rows.map(([name, meaning]) => (
            // Phones: name above meaning; from sm on two columns.
            <tr key={name} className="block border-t border-slate-100 align-top first:border-t-0 sm:table-row dark:border-slate-800">
              <td className="block break-words px-3 pt-2 font-mono text-xs font-semibold sm:table-cell sm:whitespace-nowrap sm:pb-2">
                {name}
              </td>
              <td className="block px-3 pb-2 pt-1 sm:table-cell sm:pt-2">{meaning}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CodeBlock({ code }: { code: string }) {
  const { lang } = useI18n();
  const [copied, setCopied] = useState(false);
  const copy = () => {
    navigator.clipboard?.writeText(code).then(
      () => {
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      },
      () => undefined,
    );
  };
  return (
    <div className="relative">
      <pre className="panel overflow-x-auto p-3 pr-20 font-mono text-xs leading-relaxed">{code}</pre>
      <button type="button" className="btn absolute right-2 top-2 px-2 py-1 text-xs" onClick={copy}>
        {copied ? TEXT[lang].copied : TEXT[lang].copy}
      </button>
    </div>
  );
}

export function ApiDocsPage() {
  const { lang } = useI18n();
  const x = TEXT[lang];
  const api = `${window.location.origin}/api/convert`;
  const samples = examples(api);
  const [tab, setTab] = useState<keyof typeof samples>("curl");

  return (
    <div className="mx-auto max-w-4xl px-4 py-6 md:py-10">
      <h1 className="text-2xl font-bold tracking-tight">{x.title}</h1>
      <p className="mt-2 max-w-3xl text-sm text-slate-600 dark:text-slate-400">{x.intro}</p>

      <Section title={x.quick}>
        <CodeBlock code={`curl -F file=@fund.xlsx -F response=file -OJ ${api}`} />
      </Section>

      <Section title={x.endpoint}>
        <p>
          <code className="chip bg-slate-100 font-mono normal-case text-slate-700 dark:bg-slate-800 dark:text-slate-200">POST</code>{" "}
          <code className="font-mono text-xs">{api}</code>
        </p>
        <p>{x.endpointText}</p>
      </Section>

      <Section title={x.params}>
        <Table head={[x.colName, x.colMeaning]} rows={x.paramRows} />
      </Section>

      <Section title={x.modes}>
        <Table rows={x.modeRows} />
      </Section>

      <Section title={x.examples}>
        <div className="inline-flex rounded-full bg-slate-100 p-1 dark:bg-slate-900">
          {(Object.keys(samples) as (keyof typeof samples)[]).map((k) => (
            <button key={k} type="button" className={clsx("pill", tab === k && "pill-active")} onClick={() => setTab(k)}>
              {k}
            </button>
          ))}
        </div>
        <CodeBlock code={samples[tab]} />
      </Section>

      <Section title={x.report}>
        <Table rows={x.reportRows} />
      </Section>

      <Section title={x.headers}>
        <Table rows={x.headerRows} />
      </Section>

      <Section title={x.limits}>
        <Table rows={x.limitRows} />
      </Section>

      <Section title={x.errors}>
        <p>{x.errorsText}</p>
        <Table rows={x.errorRows} />
      </Section>

      <Section title={x.issues}>
        <p>{x.issuesText}</p>
        <Table rows={ISSUE_CODES.map((code) => [code, issueText(lang, code, "")] as Row)} />
      </Section>

      <p className="mt-8 text-sm text-slate-600 dark:text-slate-400">
        {x.openapi}{" "}
        <a className="underline" href="/api/docs">
          /api/docs
        </a>{" "}
        ·{" "}
        <a className="underline" href="/api/openapi.json">
          /api/openapi.json
        </a>
      </p>
    </div>
  );
}
