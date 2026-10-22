import clsx from "clsx";
import { useEffect, useMemo, useState } from "react";
import { fetchMapping, fetchOpenfundsMapping } from "../lib/api";
import { useI18n, type MessageKey } from "../lib/i18n";
import type { MappingField, MappingRule, OpenfundsMappingField } from "../types";

const STATUS: Record<MappingField["status"], { label: MessageKey; className: string }> = {
  "block+core": { label: "statusBoth", className: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/50 dark:text-emerald-200" },
  block: { label: "statusBlock", className: "bg-blue-100 text-blue-800 dark:bg-blue-900/50 dark:text-blue-200" },
  core: { label: "statusCore", className: "bg-violet-100 text-violet-800 dark:bg-violet-900/50 dark:text-violet-200" },
  custom: { label: "statusCustom", className: "bg-amber-100 text-amber-800 dark:bg-amber-900/50 dark:text-amber-200" },
};

const OF_STATUS: Record<OpenfundsMappingField["status"], { label: MessageKey; className: string }> = {
  core: { label: "inCore", className: STATUS.core.className },
  template: { label: "statusTemplate", className: STATUS.block.className },
  holding: { label: "statusHolding", className: STATUS["block+core"].className },
  custom: { label: "statusCustom", className: STATUS.custom.className },
};
const PAGE = 200;

type Source = "V7" | "V8" | "openfunds";

export function MappingPage() {
  const { t } = useI18n();
  const [source, setSource] = useState<Source>("V8");
  return (
    <div className="mx-auto max-w-6xl px-4 py-6 md:py-10">
      <h1 className="text-2xl font-bold tracking-tight">{t("mappingTitle")}</h1>
      <div className="mt-4 inline-flex rounded-full bg-slate-100 p-1 dark:bg-slate-900">
        {(["V7", "V8", "openfunds"] as const).map((v) => (
          <button key={v} type="button" className={clsx("pill", source === v && "pill-active")} onClick={() => setSource(v)}>
            {v === "openfunds" ? "openfunds" : `TPT ${v}`}
          </button>
        ))}
      </div>
      {source === "openfunds" ? <OpenfundsMapping /> : <TptMapping version={source} />}
    </div>
  );
}

function TptMapping({ version }: { version: "V7" | "V8" }) {
  const { t } = useI18n();
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
    <>
      <p className="mt-4 max-w-3xl text-sm text-slate-600 dark:text-slate-400">{t("mappingIntro")}</p>

      <div className="mt-5 flex flex-wrap items-center gap-3">
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
    </>
  );
}

function OpenfundsMapping() {
  const { t } = useI18n();
  const [data, setData] = useState<{ version: string; fields: OpenfundsMappingField[] } | null>(null);
  const [query, setQuery] = useState("");
  const [area, setArea] = useState("");
  const [status, setStatus] = useState<"" | OpenfundsMappingField["status"]>("");
  const [limit, setLimit] = useState(PAGE);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    fetchOpenfundsMapping()
      .then((d) => alive && setData(d))
      .catch((e) => alive && setError(String(e.message ?? e)));
    return () => {
      alive = false;
    };
  }, []);

  const fields = useMemo(() => data?.fields ?? [], [data]);
  const areas = useMemo(() => [...new Set(fields.map((f) => f.key.slice(0, 4)))], [fields]);
  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return fields.filter(
      (f) =>
        (!area || f.key.startsWith(area)) &&
        (!status || f.status === status) &&
        (!q ||
          [f.key, f.name, f.level, ...f.core.map((r) => r.path), ...f.template.map((r) => r.path)]
            .join(" ")
            .toLowerCase()
            .includes(q)),
    );
  }, [fields, query, area, status]);
  useEffect(() => setLimit(PAGE), [query, area, status]);

  const select = "rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-900";
  return (
    <>
      <p className="mt-4 max-w-3xl text-sm text-slate-600 dark:text-slate-400">
        {t("ofMappingIntro", { version: data?.version ?? "" })}
      </p>
      <div className="mt-5 flex flex-wrap items-center gap-3">
        <select className={select} value={area} onChange={(e) => setArea(e.target.value)} aria-label={t("allAreas")}>
          <option value="">{t("allAreas")}</option>
          {areas.map((a) => (
            <option key={a} value={a}>
              {a}
            </option>
          ))}
        </select>
        <select
          className={select}
          value={status}
          onChange={(e) => setStatus(e.target.value as typeof status)}
          aria-label={t("colTarget")}
        >
          <option value="">{t("all")}</option>
          {(Object.keys(OF_STATUS) as OpenfundsMappingField["status"][]).map((s) => (
            <option key={s} value={s}>
              {t(OF_STATUS[s].label)}
            </option>
          ))}
        </select>
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
              <th className="px-3 py-2">{t("colTarget")}</th>
            </tr>
          </thead>
          <tbody>
            {shown.slice(0, limit).map((f) => (
              <tr key={f.key} className="border-t border-slate-100 align-top dark:border-slate-800">
                <td className="max-w-sm px-3 py-2">
                  <div className="font-mono text-xs font-semibold">{f.key}</div>
                  <div className="text-xs">{f.name}</div>
                  <div className="mt-1 flex flex-wrap items-center gap-1">
                    <span className={clsx("chip normal-case", OF_STATUS[f.status].className)}>{t(OF_STATUS[f.status].label)}</span>
                    <span className="chip bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                      {t("colLevel")}: {f.level}
                    </span>
                  </div>
                </td>
                <td className="px-3 py-2">
                  {f.status === "custom" ? (
                    <code className="text-xs text-amber-700 dark:text-amber-400">
                      CustomAttributes/Attribute[Name=OF_{f.key}]
                    </code>
                  ) : f.status === "holding" ? (
                    <span className="text-xs">
                      TPT {f.holding.join(", ")} → <code>Fund/…/Portfolio/Positions/Position</code>,{" "}
                      <code>AssetMasterData/Asset</code>
                    </span>
                  ) : (
                    <Rules rules={[...f.core, ...f.template]} />
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {shown.length > limit && (
        <div className="mt-3 text-center">
          <button type="button" className="btn" onClick={() => setLimit(limit + PAGE)}>
            {t("moreRows", { n: Math.min(PAGE, shown.length - limit) })}
          </button>
        </div>
      )}
    </>
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
