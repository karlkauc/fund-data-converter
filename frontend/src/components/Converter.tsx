import clsx from "clsx";
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, convertFile, fetchSample, type SampleName } from "../lib/api";
import { ACCEPT, FORMAT_LABEL, FORMATS, guessSource, makeDirection, parseDirection, routeOf } from "../lib/directions";
import { openFeedback, setFeedbackContext } from "../lib/feedback";
import { useI18n, type MessageKey } from "../lib/i18n";
import { navigate } from "../lib/router";
import type { ConvertOptions, ConvertResult, Direction, Format } from "../types";
import { DropZone } from "./DropZone";
import { Faq } from "./Faq";
import { OptionsPanel } from "./OptionsPanel";
import { ResultView } from "./ResultView";

const DEFAULTS: ConvertOptions = {
  tptVersion: "",
  includeBlock: true,
  includeCore: true,
  outputFormat: "xlsx",
  delimiter: "semicolon",
  ofHeaderNames: false,
  nonOpenfundsColumns: true,
};

const DROP_HINT: Record<Format, MessageKey> = {
  tpt: "dropHintTpt",
  fundsxml: "dropHintXml",
  openfunds: "dropHintOpenfunds",
};
const SAMPLES: Record<Format, { name: SampleName; label: MessageKey }[]> = {
  tpt: [
    { name: "tpt-v7", label: "sampleV7" },
    { name: "tpt-v8", label: "sampleV8" },
  ],
  fundsxml: [{ name: "fundsxml", label: "sampleXml" }],
  openfunds: [{ name: "openfunds", label: "sampleOpenfunds" }],
};

export function Converter({ direction }: { direction: Direction }) {
  const { t } = useI18n();
  const [file, setFile] = useState<File | null>(null);
  const [options, setOptions] = useState<ConvertOptions>(DEFAULTS);
  const [result, setResult] = useState<ConvertResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const abort = useRef<AbortController | null>(null);
  // The format of the current file as far as the browser can tell, and whether the next change of
  // direction only follows the server (which detected another format than guessed).
  const fileSource = useRef<Format | null>(null);
  const following = useRef(false);
  const { source, target } = parseDirection(direction);

  const run = useCallback(async (f: File, opts: ConvertOptions, to: Format) => {
    abort.current?.abort();
    const ctrl = new AbortController();
    abort.current = ctrl;
    setBusy(true);
    setError(null);
    try {
      const res = await convertFile(f, opts, to, ctrl.signal);
      if (ctrl.signal.aborted) return;
      setResult(res);
      // The server knows the format for sure (an XLSX may be TPT or openfunds): follow it.
      fileSource.current = parseDirection(res.direction).source;
      if (routeOf(res.direction) !== window.location.pathname.replace(/^\/+|\/+$/g, "")) {
        following.current = true;
        navigate(routeOf(res.direction));
      }
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
      // The file decides the source: a .xml dropped on the TPT page is converted from FundsXML.
      const from = guessSource(f, source);
      const dir = makeDirection(from, target);
      fileSource.current = from;
      if (dir !== direction) {
        following.current = true;
        navigate(routeOf(dir));
      }
      setFile(f);
      setResult(null);
      void run(f, options, parseDirection(dir).target);
    },
    [direction, source, target, options, run],
  );

  const onOptions = (next: ConvertOptions) => {
    setOptions(next);
    if (file) void run(file, next, target);
  };

  const reset = () => {
    abort.current?.abort();
    fileSource.current = null;
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

  // Another target converts the file again; another source starts over.
  useEffect(() => {
    if (following.current) {
      following.current = false;
      return;
    }
    if (!file) return;
    if (fileSource.current === source) void run(file, options, target);
    else reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [direction]);

  const loadSample = async (name: SampleName) => {
    try {
      onFile(await fetchSample(name));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

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
          <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
            <FormatPicker
              label={t("from")}
              formats={FORMATS}
              current={source}
              onPick={(f) => navigate(routeOf(makeDirection(f, target)))}
            />
            <span aria-hidden className="text-slate-400">
              →
            </span>
            <FormatPicker
              label={t("to")}
              formats={FORMATS.filter((f) => f !== source)}
              current={target}
              onPick={(f) => navigate(routeOf(makeDirection(source, f)))}
            />
          </div>
          {file && (
            <button type="button" className="btn" onClick={reset}>
              ↺ {t("newFile")}
            </button>
          )}
        </div>

        {!file && (
          <>
            <DropZone accept={ACCEPT[source]} hint={t(DROP_HINT[source])} onFile={onFile} />
            <p className="flex flex-wrap items-center justify-center gap-2 text-sm text-slate-600 dark:text-slate-400">
              {t("trySample")}
              {SAMPLES[source].map((sample) => (
                <button key={sample.name} type="button" className="btn" onClick={() => loadSample(sample.name)}>
                  {t(sample.label)}
                </button>
              ))}
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
                <button type="button" className="btn" onClick={() => run(file, options, target)}>
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
      {!file && <Faq />}
    </div>
  );
}

function FormatPicker({
  label,
  formats,
  current,
  onPick,
}: {
  label: string;
  formats: Format[];
  current: Format;
  onPick: (f: Format) => void;
}) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-xs font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400">{label}</span>
      <div className="inline-flex rounded-full bg-slate-100 p-1 dark:bg-slate-900" role="radiogroup" aria-label={label}>
        {formats.map((f) => (
          <button
            key={f}
            type="button"
            role="radio"
            aria-checked={current === f}
            className={clsx("pill", current === f && "pill-active")}
            onClick={() => onPick(f)}
          >
            {FORMAT_LABEL[f]}
          </button>
        ))}
      </div>
    </div>
  );
}
