import { Converter } from "./components/Converter";
import { Header } from "./components/Header";
import { MappingPage } from "./components/MappingPage";
import { useI18n } from "./lib/i18n";
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
        ) : (
          <Converter direction={route === "fundsxml-to-tpt" ? "fundsxml-to-tpt" : "tpt-to-fundsxml"} />
        )}
      </main>
      <footer className="border-t border-slate-200 py-5 text-center text-xs text-slate-500 dark:border-slate-800 dark:text-slate-400">
        {t("footer")} · FinDatEx TPT V7/V8 · FundsXML 4.2.11
      </footer>
    </div>
  );
}
