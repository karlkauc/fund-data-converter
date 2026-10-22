import clsx from "clsx";
import { useMemo, useState } from "react";
import { parseDirection } from "../lib/directions";
import { downloadBase64, formatBytes } from "../lib/download";
import { issueText, useI18n, type MessageKey } from "../lib/i18n";
import type { ConvertResult, CoverageField, Format, Issue } from "../types";
import { XmlCode } from "./XmlCode";

export function ResultView({ result }: { result: ConvertResult }) {
  return (
    <div className="space-y-4">
      <InputLine result={result} />
      <div className="grid gap-4 md:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
        <SummaryCard result={result} />
        <CoverageCard result={result} />
      </div>
      <IssuesPanel issues={result.issues} />
      {result.validation && !result.validation.valid && <ValidationPanel errors={result.validation.errors} />}
      <PreviewPanel result={result} />
      <DownloadBar result={result} />
    </div>
  );
}

/** "TPT V7", "openfunds 2.13.0", "FundsXML 4.2.11". */
function formatLabel(format: Format, version: string | undefined, schema: string): string {
  if (format === "fundsxml") return `FundsXML ${schema}`;
  return `${format === "tpt" ? "TPT" : "openfunds"}${version ? ` ${version}` : ""}`;
}

function InputLine({ result }: { result: ConvertResult }) {
  const { t } = useI18n();
  const { input } = result;
  const { source: from, target: to } = parseDirection(result.direction);
  const schema = result.meta?.fundsxmlSchema ?? "4";
  const inLabel = formatLabel(from, from === "fundsxml" ? undefined : input.version, schema);
  const outLabel = formatLabel(to, from === "fundsxml" ? input.version : input.outputVersion, schema);
  const source =
    input.kind === "fundsxml"
      ? input.source === "core"
        ? t("sourceCore")
        : input.source === "block+core"
          ? t("sourceBoth")
          : t("sourceBlock")
      : null;
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
      <span className="font-medium">{input.filename}</span>
      <span className="chip bg-blue-100 text-blue-800 dark:bg-blue-900/60 dark:text-blue-200">{inLabel}</span>
      <span aria-hidden className="text-slate-400">
        →
      </span>
      <span className="chip bg-emerald-100 text-emerald-800 dark:bg-emerald-900/60 dark:text-emerald-200">{outLabel}</span>
      {input.kind === "openfunds" && (
        <span className="text-slate-500 dark:text-slate-400">
          {input.format?.toUpperCase()}
          {input.delimiter ? ` (${input.delimiter === "\t" ? "Tab" : input.delimiter})` : ""} · {input.layout} · {input.columns}{" "}
          {t("columnsLabel")}
        </span>
      )}
      {input.kind === "tpt" && (
        <span className="text-slate-500 dark:text-slate-400">
          {t("detected")} {t("via")} {sourceLabel(input.versionSource, t)} · {input.format?.toUpperCase()}
          {input.delimiter ? ` (${input.delimiter === "\t" ? "Tab" : input.delimiter})` : ""} · {input.columns}{" "}
          {t("columnsLabel")}
        </span>
      )}
      {source && <span className="text-slate-500 dark:text-slate-400">{source}</span>}
    </div>
  );
}

function sourceLabel(source: string | undefined, t: (k: MessageKey) => string): string {
  if (source === "field 1000") return `${t("field")} 1000`;
  if (source === "fields 150/151") return `${t("fields")} 150/151`;
  if (source === "user") return t("userChoice");
  return t("defaultVersion");
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="flex items-baseline justify-between gap-4 py-1">
      <dt className="text-sm text-slate-500 dark:text-slate-400">{label}</dt>
      <dd className="font-semibold tabular-nums">{value}</dd>
    </div>
  );
}

function SummaryCard({ result }: { result: ConvertResult }) {
  const { t } = useI18n();
  const dates = [...new Set(result.summary.portfolioList.map((p) => p.date).filter(Boolean))];
  return (
    <section className="panel p-4" aria-labelledby="overview-title">
      <h2 id="overview-title" className="panel-title mb-2">
        {t("overview")}
      </h2>
      <dl className="divide-y divide-slate-100 dark:divide-slate-800">
        {result.summary.funds !== undefined && <Stat label={t("funds")} value={result.summary.funds} />}
        {result.summary.shareclasses !== undefined && (
          <Stat label={t("shareclasses")} value={result.summary.shareclasses} />
        )}
        {result.summary.portfolios !== undefined && <Stat label={t("portfolios")} value={result.summary.portfolios} />}
        <Stat label={t("positions")} value={result.summary.positions} />
        {result.summary.assets !== undefined && <Stat label={t("assets")} value={result.summary.assets} />}
        <Stat label={t("valuationDate")} value={dates.join(", ") || "–"} />
      </dl>
      {result.summary.portfolioList.length > 0 && (
        <ul className="mt-3 space-y-1 text-xs text-slate-600 dark:text-slate-300">
          {result.summary.portfolioList.slice(0, 6).map((p) => (
            <li key={`${p.id}-${p.date}`} className="truncate">
              <span className="font-mono">{p.id || "–"}</span> · {p.name || "–"} · {p.positions} {t("positions")}
            </li>
          ))}
          {result.summary.portfolioList.length > 6 && <li>…</li>}
        </ul>
      )}
    </section>
  );
}

function CoverageCard({ result }: { result: ConvertResult }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const cov = result.coverage;
  const { source: from, target: to } = parseDirection(result.direction);
  if (to !== "fundsxml") {
    const total = cov.total ?? cov.present;
    return (
      <section className="panel p-4" aria-labelledby="coverage-title">
        <h2 id="coverage-title" className="panel-title mb-3">
          {t("coverage")}
        </h2>
        <Bar parts={[{ value: cov.present, className: "bg-accent dark:bg-accent-dark" }]} total={total} />
        <p className="mt-2 text-sm">
          <strong className="tabular-nums">
            {cov.present} / {total}
          </strong>{" "}
          {t("fieldsInFile")}
        </p>
      </section>
    );
  }
  const blockOrCore = cov.fields.filter((f) => f.block || f.core).length;
  return (
    <section className="panel p-4" aria-labelledby="coverage-title">
      <div className="mb-3 flex items-center justify-between">
        <h2 id="coverage-title" className="panel-title">
          {t("coverage")}
        </h2>
        <button type="button" className="text-xs text-accent underline dark:text-accent-dark" onClick={() => setOpen(!open)}>
          {t("details")} {open ? "▴" : "▾"}
        </button>
      </div>
      <Bar
        total={cov.present}
        parts={[
          { value: blockOrCore, className: "bg-accent dark:bg-accent-dark" },
          { value: cov.present - blockOrCore, className: "bg-amber-400" },
        ]}
      />
      <p className="mt-2 text-sm">
        <strong className="tabular-nums">{cov.present}</strong> {t("fieldsInFile")}
      </p>
      <ul className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-sm text-slate-600 dark:text-slate-300">
        {from === "tpt" && (
          <li>
            <Dot className="bg-accent dark:bg-accent-dark" /> {t("inBlock")}: <strong>{cov.block}</strong>
          </li>
        )}
        <li>
          <Dot className="bg-accent dark:bg-accent-dark" /> {t("inCore")}: <strong>{cov.core}</strong>
        </li>
        <li>
          <Dot className="bg-amber-400" /> {t("asCustom")}: <strong>{cov.custom}</strong>
        </li>
      </ul>
      {open && <CoverageTable fields={cov.fields} block={from === "tpt"} />}
    </section>
  );
}

function CoverageTable({ fields, block }: { fields: CoverageField[]; block: boolean }) {
  const { t } = useI18n();
  const mark = (on: boolean) => (on ? "✓" : "");
  return (
    <div className="mt-3 max-h-72 overflow-auto rounded border border-slate-200 dark:border-slate-800">
      <table className="w-full text-xs">
        <thead className="sticky top-0 bg-slate-100 text-left dark:bg-slate-800">
          <tr>
            <th className="px-2 py-1">{t("colField")}</th>
            {block && <th className="px-2 py-1 text-center">{t("inBlock")}</th>}
            <th className="px-2 py-1 text-center">{t("inCore")}</th>
            <th className="px-2 py-1 text-center">{t("asCustom")}</th>
          </tr>
        </thead>
        <tbody>
          {fields.map((f) => (
            <tr key={f.key} className="border-t border-slate-100 dark:border-slate-800">
              <td className="px-2 py-0.5 font-mono">{f.name.startsWith(f.key) ? f.name : `${f.key} ${f.name}`}</td>
              {block && <td className="px-2 py-0.5 text-center text-blue-600 dark:text-blue-300">{mark(f.block)}</td>}
              <td className="px-2 py-0.5 text-center text-blue-600 dark:text-blue-300">{mark(f.core)}</td>
              <td className="px-2 py-0.5 text-center text-amber-600">{mark(f.custom)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Dot({ className }: { className: string }) {
  return <span className={clsx("mr-1 inline-block h-2 w-2 rounded-full align-middle", className)} aria-hidden />;
}

function Bar({ parts, total }: { parts: { value: number; className: string }[]; total: number }) {
  return (
    <div className="flex h-2.5 w-full overflow-hidden rounded-full bg-slate-200 dark:bg-slate-800" aria-hidden>
      {parts.map((p, i) => (
        <div key={i} className={p.className} style={{ width: `${total ? (p.value / total) * 100 : 0}%` }} />
      ))}
    </div>
  );
}

const LEVEL_STYLE: Record<Issue["level"], { icon: string; className: string }> = {
  error: { icon: "✖", className: "text-red-600 dark:text-red-400" },
  warning: { icon: "⚠", className: "text-amber-600 dark:text-amber-400" },
  info: { icon: "ℹ", className: "text-blue-600 dark:text-blue-300" },
};

function IssuesPanel({ issues }: { issues: Issue[] }) {
  const { t, lang } = useI18n();
  const [filter, setFilter] = useState<"all" | Issue["level"]>("all");
  const shown = useMemo(() => issues.filter((i) => filter === "all" || i.level === filter), [issues, filter]);
  const count = (l: Issue["level"]) => issues.filter((i) => i.level === l).length;
  const filters: { key: "all" | Issue["level"]; label: MessageKey; n: number }[] = [
    { key: "all", label: "all", n: issues.length },
    { key: "error", label: "errors", n: count("error") },
    { key: "warning", label: "warnings", n: count("warning") },
    { key: "info", label: "infos", n: count("info") },
  ];
  return (
    <details className="panel p-4" open={issues.length === 0 || issues.some((i) => i.level !== "info")}>
      <summary className="flex cursor-pointer flex-wrap items-center justify-between gap-2">
        <h2 className="panel-title inline">
          {t("issues")} ({issues.length})
        </h2>
      </summary>
      {issues.length === 0 ? (
        <p className="mt-3 text-sm text-emerald-700 dark:text-emerald-400">✓ {t("noIssues")}</p>
      ) : (
        <>
          <div className="mt-3 flex flex-wrap gap-1" role="group">
            {filters
              .filter((f) => f.key === "all" || f.n > 0)
              .map((f) => (
                <button
                  key={f.key}
                  type="button"
                  className={clsx("pill text-xs", filter === f.key && "pill-active")}
                  onClick={() => setFilter(f.key)}
                  aria-pressed={filter === f.key}
                >
                  {t(f.label)} {f.n}
                </button>
              ))}
          </div>
          <ul className="mt-3 max-h-80 space-y-1.5 overflow-auto text-sm">
            {shown.map((i, idx) => (
              <li key={idx} className="flex gap-2">
                <span className={clsx("shrink-0", LEVEL_STYLE[i.level].className)} aria-label={i.level}>
                  {LEVEL_STYLE[i.level].icon}
                </span>
                <span className="min-w-0">
                  {i.hop && (
                    <span className="chip mr-1 bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                      {t("hopStep")}
                    </span>
                  )}
                  {i.row !== undefined && (
                    <span className="mr-1 font-medium">
                      {t("row")} {i.row}
                    </span>
                  )}
                  {i.field && (
                    <span className="mr-1 font-medium">
                      {i.field.includes(",") ? t("fields") : t("field")} {i.field.replace(/,/g, ", ")}:
                    </span>
                  )}
                  {issueText(lang, i.code, i.message, i.params)}
                  {i.detail && <span className="text-slate-500 dark:text-slate-400"> ({i.detail})</span>}
                  {i.value && <span className="ml-1 font-mono text-slate-500">„{i.value}“</span>}
                  {i.path && (
                    <span className="block truncate font-mono text-xs text-slate-400" title={i.path}>
                      {i.path.replace(/^FundsXML4\//, "")}
                    </span>
                  )}
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
    </details>
  );
}

function ValidationPanel({ errors }: { errors: string[] }) {
  const { t } = useI18n();
  return (
    <details className="panel border-amber-300 p-4 dark:border-amber-700">
      <summary className="cursor-pointer text-sm font-medium text-amber-700 dark:text-amber-400">
        ⚠ {t("xsdInvalid", { n: errors.length })}
      </summary>
      <ul className="mt-2 max-h-72 space-y-1 overflow-auto font-mono text-xs">
        {errors.map((e, i) => (
          <li key={i} className="break-all">
            {e}
          </li>
        ))}
      </ul>
    </details>
  );
}

function PreviewPanel({ result }: { result: ConvertResult }) {
  const { t } = useI18n();
  const [tab, setTab] = useState<"table" | "xml">("table");
  const { preview } = result;
  return (
    <details className="panel p-4" open>
      <summary className="flex cursor-pointer items-center justify-between">
        <h2 className="panel-title inline">{t("preview")}</h2>
      </summary>
      {result.xmlPreview && (
        <div className="mt-3 flex gap-1">
          <button type="button" className={clsx("pill text-xs", tab === "table" && "pill-active")} onClick={() => setTab("table")}>
            {t("table")}
          </button>
          <button type="button" className={clsx("pill text-xs", tab === "xml" && "pill-active")} onClick={() => setTab("xml")}>
            {t("xml")}
          </button>
        </div>
      )}
      {tab === "table" || !result.xmlPreview ? (
        <>
          <div className="mt-3 max-h-[28rem] overflow-auto rounded border border-slate-200 dark:border-slate-800">
            <table className="w-full whitespace-nowrap text-xs">
              <thead className="sticky top-0 bg-slate-100 text-left dark:bg-slate-800">
                <tr>
                  <th className="px-2 py-1.5">#</th>
                  {preview.columns.map((c) => (
                    <th key={c.key} className="px-2 py-1.5 font-medium" title={c.name}>
                      {c.name.replace(/_/g, " ")}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {preview.rows.map((row, i) => (
                  <tr key={i} className="border-t border-slate-100 odd:bg-slate-50/50 dark:border-slate-800 dark:odd:bg-slate-900/40">
                    <td className="px-2 py-1 text-slate-400">{i + 1}</td>
                    {row.map((cell, j) => (
                      <td key={j} className="max-w-[16rem] truncate px-2 py-1 font-mono" title={cell}>
                        {cell}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-1 text-xs text-slate-500">
            {t("firstRows", { n: Math.min(preview.rows.length, preview.total), total: preview.total })}
          </p>
        </>
      ) : (
        <XmlCode xml={result.xmlPreview} truncated={result.xmlPreviewTruncated} />
      )}
    </details>
  );
}

function DownloadBar({ result }: { result: ConvertResult }) {
  const { t } = useI18n();
  const { output, validation } = result;
  return (
    <div className="sticky bottom-0 z-10 -mx-4 border-t border-slate-200 bg-white/95 px-4 py-3 backdrop-blur dark:border-slate-800 dark:bg-slate-900/95 md:mx-0 md:rounded-lg md:border">
      <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-center gap-3">
        <button
          type="button"
          className="btn btn-primary px-5 py-2.5 text-base"
          onClick={() => downloadBase64(output.base64, output.filename, output.mimeType)}
        >
          <span>⬇ {t("download")}</span>
          <span className="hidden max-w-[22rem] truncate sm:inline">{output.filename}</span>
          <span className="text-xs opacity-80">({formatBytes(output.size)})</span>
        </button>
        {validation &&
          (validation.valid ? (
            <span className="text-sm text-emerald-700 dark:text-emerald-400">✓ {t("xsdValid")}</span>
          ) : (
            <span className="text-sm text-amber-700 dark:text-amber-400">⚠ {t("xsdInvalid", { n: validation.errors.length })}</span>
          ))}
      </div>
    </div>
  );
}
