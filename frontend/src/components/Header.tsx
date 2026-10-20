import { useEffect, useState } from "react";
import { useI18n } from "../lib/i18n";
import { navigate, type Route } from "../lib/router";

type Theme = "light" | "dark";

function readTheme(): Theme {
  return document.documentElement.classList.contains("dark") ? "dark" : "light";
}

function ThemeToggle() {
  const { t } = useI18n();
  const [theme, setTheme] = useState<Theme>(readTheme);
  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
    try {
      localStorage.setItem("tptfx-theme", theme);
    } catch {
      // storage blocked
    }
  }, [theme]);
  return (
    <button
      type="button"
      className="btn px-2.5"
      onClick={() => setTheme((p) => (p === "dark" ? "light" : "dark"))}
      aria-label={t("theme")}
      title={t("theme")}
    >
      {theme === "dark" ? "☾" : "☀"}
    </button>
  );
}

export function Header({ route }: { route: Route }) {
  const { t, lang, setLang } = useI18n();
  return (
    <header className="sticky top-0 z-20 border-b border-slate-200 bg-slate-50/90 backdrop-blur dark:border-slate-800 dark:bg-slate-900/90">
      <div className="mx-auto flex max-w-6xl items-center gap-3 px-4 py-2.5">
        <a
          href="/"
          onClick={(e) => {
            e.preventDefault();
            navigate("");
          }}
          className="flex items-center gap-2 font-semibold tracking-tight"
        >
          <img src="/favicon.svg" alt="" className="h-7 w-7" />
          <span className="hidden sm:inline">{t("appTitle")}</span>
          <span className="sm:hidden">TPT ⇄ FundsXML</span>
        </a>
        <nav className="ml-auto flex items-center gap-1.5">
          <a
            href="/mapping"
            onClick={(e) => {
              e.preventDefault();
              navigate("mapping");
            }}
            className={`btn ${route === "mapping" ? "btn-primary" : ""}`}
            aria-current={route === "mapping" ? "page" : undefined}
          >
            <span aria-hidden>⇆</span>
            <span className="hidden sm:inline">{t("mapping")}</span>
          </a>
          <button
            type="button"
            className="btn px-2.5"
            onClick={() => setLang(lang === "de" ? "en" : "de")}
            title={t("language")}
            aria-label={t("language")}
          >
            {lang === "de" ? "EN" : "DE"}
          </button>
          <ThemeToggle />
        </nav>
      </div>
    </header>
  );
}
