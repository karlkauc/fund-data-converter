import { useEffect, useState } from "react";
import { fetchFaq } from "../lib/api";
import { useI18n } from "../lib/i18n";
import type { FaqEntry } from "../types";

/** The home FAQ – the same entries the server renders into the shell and its FAQPage JSON-LD. */
export function Faq() {
  const { t } = useI18n();
  const [items, setItems] = useState<FaqEntry[]>([]);
  useEffect(() => {
    fetchFaq().then(setItems, () => setItems([]));
  }, []);
  if (!items.length) return null;
  return (
    <section className="mx-auto mt-12 max-w-3xl" aria-labelledby="faq-title">
      <h2 id="faq-title" className="mb-3 text-lg font-semibold">{t("faqTitle")}</h2>
      <div className="divide-y divide-slate-200 rounded-lg border border-slate-200 bg-white dark:divide-slate-800 dark:border-slate-800 dark:bg-slate-900">
        {items.map((item) => (
          <details key={item.question} className="group px-4 py-3">
            <summary className="cursor-pointer font-medium">
              {item.question}
            </summary>
            {/* Server-rendered Markdown from our own faq.toml (raw HTML disabled there). */}
            <div
              className="faq-answer mt-2 text-sm text-slate-700 dark:text-slate-300"
              dangerouslySetInnerHTML={{ __html: item.answer_html }}
            />
          </details>
        ))}
      </div>
    </section>
  );
}
