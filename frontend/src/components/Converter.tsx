import clsx from "clsx";
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, convertFile, fetchSample } from "../lib/api";
import { openFeedback, setFeedbackContext } from "../lib/feedback";
import { useI18n } from "../lib/i18n";
import { navigate } from "../lib/router";
import type { ConvertOptions, ConvertResult, Direction } from "../types";
import { DropZone } from "./DropZone";
import { OptionsPanel } from "./OptionsPanel";
import { ResultView } from "./ResultView";

const DEFAULTS: ConvertOptions = {
  tptVersion: "",
  includeBlock: true,
  includeCore: true,
  outputFormat: "xlsx",
  delimiter: "semicolon",
};

function directionOf(file: File): Direction {
  return file.name.toLowerCase().endsWith(".xml") ? "fundsxml-to-tpt" : "tpt-to-fundsxml";
}

export function Converter({ direction }: { direction: Direction }) {
  const { t } = useI18n();
  const [file, setFile] = useState<File | null>(null);
  const [options, setOptions] = useState<ConvertOptions>(DEFAULTS);
  const [result, setResult] = useState<ConvertResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const abort = useRef<AbortController | null>(null);

  const run = useCallback(async (f: File, opts: ConvertOptions) => {
    abort.current?.abort();
    const ctrl = new AbortController();
    abort.current = ctrl;
    setBusy(true);
    setError(null);
    try {
      const res = await convertFile(f, opts, ctrl.signal);
      if (!ctrl.signal.aborted) setResult(res);
    } catch (e) {
      if (ctrl.signal.aborted) return;
      setResult(null);
      setError(e instanceof ApiError || e instanceof Error ? e.message : String(e));
    } finally {
      if (!ctrl.signal.aborted) setBusy(false);
    }
  }, []);

  const onFile = useCallback(
    (f: File) => {
      // The file decides the direction: a .xml dropped on the TPT tab is converted to TPT.
      const dir = directionOf(f);
      if (dir !== direction) navigate(dir === "tpt-to-fundsxml" ? "" : "fundsxml-to-tpt");
      setFile(f);
      setResult(null);
      void run(f, options);
    },
    [direction, options, run],
  );

  const onOptions = (next: ConvertOptions) => {
    setOptions(next);
    if (file) void run(file, next);
  };

  const reset = () => {
    abort.current?.abort();
    setFile(null);
    setResult(null);
    setError(null);
    setBusy(false);
  };

  // Feedback sent while a conversion is open says which direction and version it was about.
  useEffect(() => {
    setFeedbackContext(file ? { direction, tptVersion: result?.input.version || options.tptVersion || undefined } : {});
    return () => setFeedbackContext({});
  }, [file, direction, result, options.tptVersion]);

  // Switching tabs without a file in progress starts over.
  useEffect(() => {
    if (file && directionOf(file) !== direction) reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [direction]);

  const loadSample = async (name: "tpt-v7" | "tpt-v8" | "fundsxml") => {
    try {
      onFile(await fetchSample(name));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const toFundsxml = direction === "tpt-to-fundsxml";

  return (
    <div className="mx-auto max-w-6xl px-4 py-6 md:py-10">
      {!file && (
        <div className="mx-auto mb-6 max-w-3xl text-center">
          <h1 className="text-2xl font-bold tracking-tight md:text-3xl">{t("tagline")}</h1>
          <p className="mt-2 text-sm text-slate-600 dark:text-slate-400">{t("privacy")}</p>
        </div>
      )}

      <div className={clsx("mx-auto space-y-4", !file && "max-w-3xl")}>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="inline-flex rounded-full bg-slate-100 p-1 dark:bg-slate-900" role="tablist">
            <button
              type="button"
              role="tab"
              aria-selected={toFundsxml}
              className={clsx("pill", toFundsxml && "pill-active")}
              onClick={() => navigate("")}
            >
              {t("dirToFundsxml")}
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={!toFundsxml}
              className={clsx("pill", !toFundsxml && "pill-active")}
              onClick={() => navigate("fundsxml-to-tpt")}
            >
              {t("dirToTpt")}
            </button>
          </div>
          {file && (
            <button type="button" className="btn" onClick={reset}>
              ↺ {t("newFile")}
            </button>
          )}
        </div>

        {!file && (
          <>
            <DropZone
              accept={toFundsxml ? ".xlsx,.xlsm,.csv,.txt,.tsv" : ".xml"}
              hint={toFundsxml ? t("dropHintTpt") : t("dropHintXml")}
              onFile={onFile}
            />
            <p className="flex flex-wrap items-center justify-center gap-2 text-sm text-slate-600 dark:text-slate-400">
              {t("trySample")}
              {toFundsxml ? (
                <>
                  <button type="button" className="btn" onClick={() => loadSample("tpt-v7")}>
                    {t("sampleV7")}
                  </button>
                  <button type="button" className="btn" onClick={() => loadSample("tpt-v8")}>
                    {t("sampleV8")}
                  </button>
                </>
              ) : (
                <button type="button" className="btn" onClick={() => loadSample("fundsxml")}>
                  {t("sampleXml")}
                </button>
              )}
            </p>
          </>
        )}

        <OptionsPanel direction={direction} options={options} onChange={onOptions} disabled={busy} />

        {busy && (
          <div className="panel flex items-center gap-3 p-4 text-sm" role="status">
            <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-accent border-t-transparent" />
            {t("converting")} {file?.name}
          </div>
        )}

        {error && !busy && (
          <div className="panel border-red-300 p-4 text-sm dark:border-red-800" role="alert">
            <p className="font-semibold text-red-700 dark:text-red-400">✖ {t("error")}</p>
            <p className="mt-1">{error}</p>
            <div className="mt-3 flex flex-wrap gap-2">
              {file && (
                <button type="button" className="btn" onClick={() => run(file, options)}>
                  {t("retry")}
                </button>
              )}
              <button type="button" className="btn" onClick={() => openFeedback({ errorDetail: error })}>
                {t("reportProblem")}
              </button>
            </div>
          </div>
        )}

        {result && !busy && <ResultView result={result} />}
      </div>
    </div>
  );
}
