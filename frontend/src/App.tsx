import { ApiDocsPage } from "./components/ApiDocsPage";
import { Converter } from "./components/Converter";
import { FeedbackDialog } from "./components/FeedbackDialog";
import { Header } from "./components/Header";
import { MappingPage } from "./components/MappingPage";
import { openFeedback } from "./lib/feedback";
import { useI18n } from "./lib/i18n";
import { FAMILY, FIELDS_URL, GUIDES_URL, IMPRINT_URL, MESSAGES_URL, OPENFUNDS_FIELDS_URL, PRIVACY_URL } from "./lib/links";
import { directionOf } from "./lib/directions";
import { useRoute } from "./lib/router";

export default function App() {
  const route = useRoute();
  const { t } = useI18n();
  return (
    <div className="flex min-h-full flex-col">
      <Header route={route} />
      <main className="flex-1">
        {route === "mapping" ? (
          <MappingPage />
        ) : route === "api-docs" ? (
          <ApiDocsPage />
        ) : (
          <Converter direction={directionOf(route) ?? "tpt-to-fundsxml"} />
        )}
      </main>
      <footer className="space-y-1.5 border-t border-slate-200 py-5 text-center text-xs text-slate-500 dark:border-slate-800 dark:text-slate-400">
        <p>
          {t("footer")} · FinDatEx TPT V7/V8 · FundsXML 4.2.11 · openfunds 2.13 ·{" "}
          <button type="button" className="underline hover:text-slate-700 dark:hover:text-slate-200" onClick={() => openFeedback()}>
            {t("feedback")}
          </button>
        </p>
        <p>
          <a className="underline" href={GUIDES_URL}>{t("guides")}</a> ·{" "}
          <a className="underline" href={FIELDS_URL}>{t("allFields")}</a> ·{" "}
          <a className="underline" href={OPENFUNDS_FIELDS_URL}>{t("allOpenfundsFields")}</a> ·{" "}
          <a className="underline" href={MESSAGES_URL}>{t("messages")}</a> ·{" "}
          <a className="underline" href={IMPRINT_URL}>{t("imprint")}</a> ·{" "}
          <a className="underline" href={PRIVACY_URL}>{t("privacyPolicy")}</a>
        </p>
        <p>
          {t("family")}{" "}
          {FAMILY.map((f, i) => (
            <span key={f.key}>
              {i > 0 && " · "}
              <a className="underline" href={f.href}>
                {f.key === "desktop" ? `${f.label} (${t("desktopApp")})` : f.label}
              </a>
            </span>
          ))}
        </p>
      </footer>
      <FeedbackDialog />
    </div>
  );
}
