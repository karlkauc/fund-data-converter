import { SAMPLE_FILES, sampleUrl, samplesOf, type SampleName } from "../lib/api";
import { SAMPLE_TEXT, useI18n } from "../lib/i18n";
import type { Format } from "../types";

/** The example files of a source format: a click loads one, ⤓ saves it. */
export function SampleCards({ format, onLoad }: { format: Format; onLoad: (name: SampleName) => void }) {
  const { t, lang } = useI18n();
  return (
    <section aria-labelledby="samples-title">
      <h2 id="samples-title" className="mb-2 text-center text-sm text-slate-600 dark:text-slate-400">
        {t("trySample")}
      </h2>
      <ul className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3" data-testid="samples">
        {samplesOf(format).map((name) => {
          const [title, desc] = SAMPLE_TEXT[lang][name];
          const faulty = name.endsWith("-errors");
          return (
            <li key={name} className="panel flex min-w-0 items-stretch hover:border-accent dark:hover:border-accent-dark">
              <button
                type="button"
                className="min-w-0 flex-1 rounded-l-lg px-3 py-2 text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-accent"
                onClick={() => onLoad(name)}
                aria-describedby={`sample-${name}`}
              >
                <span className="flex flex-wrap items-center gap-1.5 text-sm font-semibold text-slate-800 dark:text-slate-100">
                  {title}
                  {faulty && (
                    <span className="chip bg-amber-100 text-amber-800 dark:bg-amber-900/50 dark:text-amber-200">
                      {t("sampleHasErrors")}
                    </span>
                  )}
                </span>
                <span id={`sample-${name}`} className="mt-0.5 block text-xs text-slate-600 dark:text-slate-400">
                  {desc}
                </span>
              </button>
              <a
                href={sampleUrl(name, true)}
                download={SAMPLE_FILES[name]}
                className="flex w-10 shrink-0 items-center justify-center rounded-r-lg border-l border-slate-200 text-slate-500 hover:bg-slate-50 hover:text-accent focus:outline-none focus-visible:ring-2 focus-visible:ring-accent dark:border-slate-800 dark:text-slate-400 dark:hover:bg-slate-800"
                aria-label={t("downloadSample", { file: SAMPLE_FILES[name] })}
                title={t("downloadSample", { file: SAMPLE_FILES[name] })}
              >
                <span aria-hidden>⤓</span>
              </a>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
