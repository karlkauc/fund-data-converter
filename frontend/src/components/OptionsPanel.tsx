import { parseDirection } from "../lib/directions";
import { useI18n } from "../lib/i18n";
import type { ConvertOptions, Direction } from "../types";

interface Props {
  direction: Direction;
  options: ConvertOptions;
  onChange: (opts: ConvertOptions) => void;
  disabled?: boolean;
}

function Radio<T extends string>({
  name,
  value,
  current,
  label,
  onSelect,
  disabled,
}: {
  name: string;
  value: T;
  current: T;
  label: string;
  onSelect: (v: T) => void;
  disabled?: boolean;
}) {
  return (
    <label className="inline-flex cursor-pointer items-center gap-1.5 text-sm">
      <input
        type="radio"
        name={name}
        value={value}
        checked={current === value}
        onChange={() => onSelect(value)}
        disabled={disabled}
        className="accent-blue-500"
      />
      {label}
    </label>
  );
}

export function OptionsPanel({ direction, options, onChange, disabled }: Props) {
  const { t } = useI18n();
  const set = (patch: Partial<ConvertOptions>) => onChange({ ...options, ...patch });
  const { source, target } = parseDirection(direction);
  const toFundsxml = direction === "tpt-to-fundsxml";
  const tptInvolved = source === "tpt" || target === "tpt";

  return (
    <details className="panel group px-4 py-3" open>
      <summary className="cursor-pointer select-none text-sm font-semibold text-slate-700 dark:text-slate-200">
        {t("options")}
      </summary>
      <div className="mt-3 grid gap-4 md:grid-cols-2">
        {tptInvolved && (
          <fieldset className="space-y-1.5">
            <legend className="field-label mb-1">{source === "tpt" ? t("tptVersionInput") : t("tptVersionOutput")}</legend>
            <div className="flex flex-wrap gap-x-4 gap-y-1">
              <Radio name="ver" value="" current={options.tptVersion} label={t("auto")} onSelect={(v) => set({ tptVersion: v })} disabled={disabled} />
              <Radio name="ver" value="V7" current={options.tptVersion} label="V7" onSelect={(v) => set({ tptVersion: v })} disabled={disabled} />
              <Radio name="ver" value="V8" current={options.tptVersion} label="V8" onSelect={(v) => set({ tptVersion: v })} disabled={disabled} />
            </div>
          </fieldset>
        )}

        {target === "openfunds" && (
          <fieldset className="space-y-1.5">
            <legend className="field-label mb-1">{t("openfundsOutput")}</legend>
            <label className="flex items-start gap-2 text-sm">
              <input
                type="checkbox"
                className="mt-0.5 accent-blue-500"
                checked={options.ofHeaderNames}
                disabled={disabled}
                onChange={(e) => set({ ofHeaderNames: e.target.checked })}
              />
              {t("ofHeaderNames")}
            </label>
            {source === "tpt" && (
              <label className="flex items-start gap-2 text-sm">
                <input
                  type="checkbox"
                  className="mt-0.5 accent-blue-500"
                  checked={options.nonOpenfundsColumns}
                  disabled={disabled}
                  onChange={(e) => set({ nonOpenfundsColumns: e.target.checked })}
                />
                {t("nonOpenfundsColumns")}
              </label>
            )}
          </fieldset>
        )}

        {target === "fundsxml" ? (
          toFundsxml && (
          <fieldset className="space-y-1.5">
            <legend className="field-label mb-1">{t("fundsxmlContent")}</legend>
            <label className="flex items-start gap-2 text-sm">
              <input
                type="checkbox"
                className="mt-0.5 accent-blue-500"
                checked={options.includeCore}
                disabled={disabled || (options.includeCore && !options.includeBlock)}
                onChange={(e) => set({ includeCore: e.target.checked })}
              />
              {t("includeCore")}
            </label>
            <label className="flex items-start gap-2 text-sm">
              <input
                type="checkbox"
                className="mt-0.5 accent-blue-500"
                checked={options.includeBlock}
                disabled={disabled || (options.includeBlock && !options.includeCore)}
                onChange={(e) => set({ includeBlock: e.target.checked })}
              />
              {t("includeBlock")}
            </label>
            {!options.includeCore && (
              <p className="text-xs text-amber-700 dark:text-amber-400" role="note">
                ⚠ {t("blockOnlyWarning")}
              </p>
            )}
          </fieldset>
          )
        ) : (
          <fieldset className="space-y-1.5">
            <legend className="field-label mb-1">{t("outputFormat")}</legend>
            <div className="flex flex-wrap gap-x-4 gap-y-1">
              <Radio name="fmt" value="xlsx" current={options.outputFormat} label="XLSX" onSelect={(v) => set({ outputFormat: v })} disabled={disabled} />
              <Radio name="fmt" value="csv" current={options.outputFormat} label="CSV" onSelect={(v) => set({ outputFormat: v })} disabled={disabled} />
            </div>
            {options.outputFormat === "csv" && (
              <label className="mt-2 flex items-center gap-2 text-sm">
                <span className="field-label">{t("delimiter")}</span>
                <select
                  className="rounded-md border border-slate-300 bg-white px-2 py-1 text-sm dark:border-slate-700 dark:bg-slate-800"
                  value={options.delimiter}
                  disabled={disabled}
                  onChange={(e) => set({ delimiter: e.target.value as ConvertOptions["delimiter"] })}
                >
                  <option value="semicolon">;</option>
                  <option value="comma">,</option>
                  <option value="pipe">|</option>
                  <option value="tab">Tab</option>
                </select>
              </label>
            )}
          </fieldset>
        )}
      </div>
    </details>
  );
}
