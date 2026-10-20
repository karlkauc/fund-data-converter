import clsx from "clsx";
import { useEffect, useMemo, useState } from "react";
import { fetchMapping } from "../lib/api";
import { useI18n, type MessageKey } from "../lib/i18n";
import type { MappingField, MappingRule } from "../types";

const STATUS: Record<MappingField["status"], { label: MessageKey; className: string }> = {
  "block+core": { label: "statusBoth", className: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/50 dark:text-emerald-200" },
  block: { label: "statusBlock", className: "bg-blue-100 text-blue-800 dark:bg-blue-900/50 dark:text-blue-200" },
  core: { label: "statusCore", className: "bg-violet-100 text-violet-800 dark:bg-violet-900/50 dark:text-violet-200" },
  custom: { label: "statusCustom", className: "bg-amber-100 text-amber-800 dark:bg-amber-900/50 dark:text-amber-200" },
};

export function MappingPage() {
  const { t } = useI18n();
  const [version, setVersion] = useState<"V7" | "V8">("V8");
  const [fields, setFields] = useState<MappingField[]>([]);
  const [query, setQuery] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    fetchMapping(version)
      .then((f) => alive && setFields(f))
      .catch((e) => alive && setError(String(e.message ?? e)));
    return () => {
      alive = false;
    };
  }, [version]);

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return fields;
    return fields.filter((f) =>
      [f.key, f.name, f.definition, ...f.block.map((r) => r.path), ...f.core.map((r) => r.path)]
        .join(" ")
        .toLowerCase()
        .includes(q),
    );
  }, [fields, query]);

  return (
    <div className="mx-auto max-w-6xl px-4 py-6 md:py-10">
      <h1 className="text-2xl font-bold tracking-tight">{t("mappingTitle")}</h1>
      <p className="mt-2 max-w-3xl text-sm text-slate-600 dark:text-slate-400">{t("mappingIntro")}</p>

      <div className="mt-5 flex flex-wrap items-center gap-3">
        <div className="inline-flex rounded-full bg-slate-100 p-1 dark:bg-slate-900">
          {(["V7", "V8"] as const).map((v) => (
            <button key={v} type="button" className={clsx("pill", version === v && "pill-active")} onClick={() => setVersion(v)}>
              TPT {v}
            </button>
          ))}
        </div>
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={t("search")}
          className="min-w-0 flex-1 rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-900"
          aria-label={t("search")}
        />
        <span className="text-xs text-slate-500">
          {shown.length} / {fields.length}
        </span>
      </div>

      {error && <p className="mt-4 text-sm text-red-600">{error}</p>}

      <div className="panel mt-4 overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-slate-100 text-left text-xs uppercase tracking-wide text-slate-500 dark:bg-slate-800 dark:text-slate-400">
            <tr>
              <th className="px-3 py-2">{t("colField")}</th>
              <th className="px-3 py-2">{t("colBlock")}</th>
              <th className="px-3 py-2">{t("colCore")}</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((f) => (
              <tr key={f.key} className="border-t border-slate-100 align-top dark:border-slate-800">
                <td className="max-w-xs px-3 py-2">
                  <div className="font-mono text-xs font-semibold">{f.name}</div>
                  <div className="mt-1 flex flex-wrap items-center gap-1">
                    <span className={clsx("chip normal-case", STATUS[f.status].className)}>{t(STATUS[f.status].label)}</span>
                    <span className="chip bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300">SII {f.flag}</span>
                  </div>
                  {f.definition && <p className="mt-1 line-clamp-3 text-xs text-slate-500 dark:text-slate-400">{f.definition}</p>}
                </td>
                <td className="px-3 py-2">
                  <Rules rules={f.block} />
                </td>
                <td className="px-3 py-2">
                  {f.status === "custom" && f.core.length === 0 ? (
                    <code className="text-xs text-amber-700 dark:text-amber-400">
                      Position/CustomAttributes/Attribute[Name=TPT_{f.name}]
                    </code>
                  ) : (
                    <Rules rules={f.core} />
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Rules({ rules }: { rules: MappingRule[] }) {
  const { t } = useI18n();
  if (!rules.length) return <span className="text-slate-400">–</span>;
  return (
    <ul className="space-y-1.5">
      {rules.map((r, i) => (
        <li key={i}>
          <code className="break-all text-xs">{r.path}</code>
          {(r.when || r.transform) && (
            <div className="text-[0.7rem] text-slate-500 dark:text-slate-400">
              {r.when && (
                <span>
                  {t("when")} {r.when}
                </span>
              )}
              {r.when && r.transform && " · "}
              {r.transform && <span>{r.transform}</span>}
            </div>
          )}
        </li>
      ))}
    </ul>
  );
}
