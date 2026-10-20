import { useMemo } from "react";
import { useI18n } from "../lib/i18n";
import { tokenizeXml, type TokenKind } from "../lib/xmlHighlight";

// Same palette as the XML tree in ../xml-online-viewer (XmlTreeView.tsx).
const CLASS: Record<TokenKind, string> = {
  punct: "text-blue-700 dark:text-blue-300",
  tag: "text-blue-700 dark:text-blue-300",
  attr: "text-amber-700 dark:text-amber-300",
  eq: "text-slate-400",
  value: "text-emerald-700 dark:text-emerald-400",
  text: "text-slate-700 dark:text-slate-300",
  comment: "text-slate-400 italic",
  decl: "text-violet-700 dark:text-violet-300",
  cdata: "text-violet-700 dark:text-violet-300",
};

export function XmlCode({ xml, truncated }: { xml: string; truncated?: boolean }) {
  const { t } = useI18n();
  const tokens = useMemo(() => tokenizeXml(xml), [xml]);
  return (
    <pre
      className="mt-3 max-h-[28rem] overflow-auto rounded border border-slate-200 bg-slate-50 p-3 font-mono text-xs dark:border-slate-800 dark:bg-slate-950"
      data-testid="xml-preview"
    >
      <code>
        {tokens.map((tok, i) => (
          <span key={i} className={CLASS[tok.kind]}>
            {tok.text}
          </span>
        ))}
      </code>
      {truncated && <div className="mt-2 italic text-slate-500 dark:text-slate-400">{t("xmlTruncated")}</div>}
    </pre>
  );
}
