import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

export type Lang = "de" | "en";

const en = {
  appTitle: "TPT ⇄ FundsXML Converter",
  tagline: "Convert TPT (V7/V8) to FundsXML 4 – and back.",
  privacy: "Files are processed in memory only and never stored. No login.",
  dirToFundsxml: "TPT → FundsXML",
  dirToTpt: "FundsXML → TPT",
  mapping: "Field mapping",
  dropTitle: "Drop a file here or",
  chooseFile: "Choose file…",
  dropHintTpt: ".xlsx · .csv · .txt (TPT V7 or V8, max. 25 MB)",
  dropHintXml: ".xml (FundsXML 4, max. 25 MB)",
  trySample: "No file at hand? Try an example:",
  sampleV7: "TPT V7",
  sampleV8: "TPT V8",
  sampleXml: "FundsXML",
  options: "Options",
  tptVersion: "TPT version",
  tptVersionInput: "TPT version of the file",
  tptVersionOutput: "TPT version to write",
  auto: "detect automatically",
  fundsxmlContent: "FundsXML content",
  includeCore: "Core structures (Fund, Position, AssetMasterData)",
  includeBlock: "Solvency II TPT block (TripartiteTemplateSolvencyII_V7)",
  blockOnlyWarning: "Without the core structures, values the TPT block cannot hold are lost.",
  outputFormat: "Output format",
  delimiter: "Delimiter",
  converting: "Converting…",
  newFile: "New file",
  detected: "detected",
  via: "via",
  overview: "Overview",
  portfolios: "Portfolios",
  positions: "Positions",
  assets: "Assets",
  valuationDate: "Valuation date",
  coverage: "Where the data went",
  fieldsInFile: "fields with values",
  inBlock: "TPT block",
  inCore: "core structures",
  asCustom: "custom attributes",
  details: "Details",
  issues: "Messages",
  noIssues: "No messages – everything was converted.",
  all: "All",
  errors: "Errors",
  warnings: "Warnings",
  infos: "Info",
  row: "row",
  field: "field",
  fields: "fields",
  userChoice: "your choice",
  defaultVersion: "default (no version field)",
  columnsLabel: "columns",
  preview: "Preview",
  table: "Table",
  xml: "XML",
  xmlTruncated: "… truncated – download the file for the full document",
  firstRows: "first {n} of {total} rows",
  download: "Download",
  xsdValid: "valid against FundsXML 4.2.11 XSD",
  xsdInvalid: "{n} XSD validation error(s)",
  showErrors: "show",
  hideErrors: "hide",
  sourceBlock: "read from the TPT block",
  sourceCore: "read from the core structures",
  sourceBoth: "read from the TPT block and custom attributes",
  error: "Conversion failed",
  retry: "Try again",
  mappingTitle: "TPT ⇄ FundsXML field mapping",
  mappingIntro:
    "Every TPT field and where it goes in FundsXML 4.2.11. Fields without a FundsXML element are kept as custom attributes (TPT_<field>) on the position, so the reverse conversion restores them.",
  search: "Search field, name or path…",
  statusBoth: "block + core",
  statusBlock: "block only",
  statusCore: "core only",
  statusCustom: "custom attribute",
  colField: "Field",
  colBlock: "TPT block",
  colCore: "Core structures",
  when: "when",
  footer: "Free · no account · no tracking · files are not stored",
  backToConverter: "Back to the converter",
  theme: "Switch theme",
  language: "Deutsch",
};

const de: typeof en = {
  appTitle: "TPT ⇄ FundsXML Converter",
  tagline: "Konvertiere TPT (V7/V8) nach FundsXML 4 – und zurück.",
  privacy: "Dateien werden nur im Speicher verarbeitet und nicht gespeichert. Kein Login.",
  dirToFundsxml: "TPT → FundsXML",
  dirToTpt: "FundsXML → TPT",
  mapping: "Feld-Mapping",
  dropTitle: "Datei hierher ziehen oder",
  chooseFile: "Datei wählen…",
  dropHintTpt: ".xlsx · .csv · .txt (TPT V7 oder V8, max. 25 MB)",
  dropHintXml: ".xml (FundsXML 4, max. 25 MB)",
  trySample: "Keine Datei zur Hand? Beispiel laden:",
  sampleV7: "TPT V7",
  sampleV8: "TPT V8",
  sampleXml: "FundsXML",
  options: "Optionen",
  tptVersion: "TPT-Version",
  tptVersionInput: "TPT-Version der Datei",
  tptVersionOutput: "Zu schreibende TPT-Version",
  auto: "automatisch erkennen",
  fundsxmlContent: "FundsXML-Inhalt",
  includeCore: "Core-Strukturen (Fund, Position, AssetMasterData)",
  includeBlock: "Solvency-II-TPT-Block (TripartiteTemplateSolvencyII_V7)",
  blockOnlyWarning: "Ohne Core-Strukturen gehen Werte verloren, die der TPT-Block nicht aufnehmen kann.",
  outputFormat: "Ausgabeformat",
  delimiter: "Trennzeichen",
  converting: "Konvertiere…",
  newFile: "Neue Datei",
  detected: "erkannt",
  via: "über",
  overview: "Übersicht",
  portfolios: "Portfolios",
  positions: "Positionen",
  assets: "Assets",
  valuationDate: "Stichtag",
  coverage: "Wohin die Daten gingen",
  fieldsInFile: "Felder mit Werten",
  inBlock: "TPT-Block",
  inCore: "Core-Strukturen",
  asCustom: "CustomAttributes",
  details: "Details",
  issues: "Hinweise",
  noIssues: "Keine Hinweise – alles wurde konvertiert.",
  all: "Alle",
  errors: "Fehler",
  warnings: "Warnungen",
  infos: "Info",
  row: "Zeile",
  field: "Feld",
  fields: "Felder",
  userChoice: "Auswahl",
  defaultVersion: "Standard (kein Versionsfeld)",
  columnsLabel: "Spalten",
  preview: "Vorschau",
  table: "Tabelle",
  xml: "XML",
  xmlTruncated: "… gekürzt – die vollständige Datei gibt es über „Herunterladen“",
  firstRows: "erste {n} von {total} Zeilen",
  download: "Herunterladen",
  xsdValid: "gültig gegen FundsXML 4.2.11 XSD",
  xsdInvalid: "{n} XSD-Validierungsfehler",
  showErrors: "anzeigen",
  hideErrors: "ausblenden",
  sourceBlock: "aus dem TPT-Block gelesen",
  sourceCore: "aus den Core-Strukturen gelesen",
  sourceBoth: "aus TPT-Block und CustomAttributes gelesen",
  error: "Konvertierung fehlgeschlagen",
  retry: "Erneut versuchen",
  mappingTitle: "TPT ⇄ FundsXML Feld-Mapping",
  mappingIntro:
    "Jedes TPT-Feld und sein Ziel in FundsXML 4.2.11. Felder ohne FundsXML-Element werden als CustomAttributes (TPT_<Feld>) an der Position abgelegt, damit die Rückkonvertierung sie wiederherstellt.",
  search: "Feld, Name oder Pfad suchen…",
  statusBoth: "Block + Core",
  statusBlock: "nur Block",
  statusCore: "nur Core",
  statusCustom: "CustomAttribute",
  colField: "Feld",
  colBlock: "TPT-Block",
  colCore: "Core-Strukturen",
  when: "wenn",
  footer: "Kostenlos · kein Konto · kein Tracking · Dateien werden nicht gespeichert",
  backToConverter: "Zurück zum Konverter",
  theme: "Farbschema wechseln",
  language: "English",
};

// Issue texts by backend issue code (app/model/issues.py); {placeholders} come from issue.params.
const ISSUES: Record<Lang, Record<string, string>> = {
  en: {
    block_value_rejected: "Not accepted by the TPT block – kept as custom attribute",
    schema_incomplete: "Mandatory FundsXML content missing or invalid",
    core_value_skipped: "Not written to the core structures (kept in the TPT block)",
    core_value_rejected: "Not accepted by the core structures – kept as custom attribute",
    control_data: "ControlData value rejected",
    portfolio_value_differs: "Differs from the first row of portfolio {portfolio}; kept as custom attribute",
    xsd_invalid: "The generated document has {n} XSD validation error(s).",
    v8_in_v7_block:
      "FundsXML 4.2.11 has no TPT V8 block: V8 data goes into the V7 block; fields 150/151, the full version label (1000) and codes e1/e2/e3 (56) are kept as custom attributes.",
    unmapped_columns: "{n} column(s) are not TPT fields and were ignored: {columns}",
    duplicate_column: "Column appears twice; the first one is used.",
    v8_fields_in_v7: "Fields 150/151 only exist in TPT V8; they are kept, but the file is treated as V7.",
    older_tpt_block: "{block} is not supported; only the V7 block and the core structures are read.",
    core_mismatch:
      "Portfolio {portfolio}: the core portfolio has {core} positions, the TPT block {block}; core data is not merged.",
    mandatory_missing: "Mandatory field {name} is empty in {n} row(s).",
    more_messages: "… {n} more message(s) of this kind",
  },
  de: {
    block_value_rejected: "Vom TPT-Block nicht übernommen – als CustomAttribute erhalten",
    schema_incomplete: "Pflichtinhalt in FundsXML fehlt oder ist ungültig",
    core_value_skipped: "Nicht in die Core-Strukturen übernommen (im TPT-Block enthalten)",
    core_value_rejected: "Von den Core-Strukturen nicht übernommen – als CustomAttribute erhalten",
    control_data: "Wert in ControlData abgelehnt",
    portfolio_value_differs: "Weicht von der ersten Zeile des Portfolios {portfolio} ab; als CustomAttribute erhalten",
    xsd_invalid: "Das erzeugte Dokument hat {n} XSD-Validierungsfehler.",
    v8_in_v7_block:
      "FundsXML 4.2.11 hat keinen TPT-V8-Block: V8-Daten werden in den V7-Block geschrieben; Felder 150/151, das vollständige Versionslabel (1000) und die Codes e1/e2/e3 (56) bleiben als CustomAttributes erhalten.",
    unmapped_columns: "{n} Spalte(n) sind keine TPT-Felder und wurden ignoriert: {columns}",
    duplicate_column: "Spalte kommt doppelt vor; die erste wird verwendet.",
    v8_fields_in_v7: "Felder 150/151 gibt es nur in TPT V8; sie bleiben erhalten, die Datei wird aber als V7 behandelt.",
    older_tpt_block: "{block} wird nicht unterstützt; gelesen werden nur der V7-Block und die Core-Strukturen.",
    core_mismatch:
      "Portfolio {portfolio}: Das Core-Portfolio hat {core} Positionen, der TPT-Block {block}; Core-Daten werden nicht übernommen.",
    mandatory_missing: "Pflichtfeld {name} ist in {n} Zeile(n) leer.",
    more_messages: "… {n} weitere Hinweis(e) dieser Art",
  },
};

export function issueText(lang: Lang, code: string, fallback: string, params?: Record<string, string | number>): string {
  let s = ISSUES[lang][code];
  if (!s) return fallback;
  if (params) for (const [k, v] of Object.entries(params)) s = s.replace(`{${k}}`, String(v));
  return s;
}

export type Messages = typeof en;
export type MessageKey = keyof Messages;
const MESSAGES: Record<Lang, Messages> = { en, de };

interface I18n {
  lang: Lang;
  setLang: (l: Lang) => void;
  t: (key: MessageKey, vars?: Record<string, string | number>) => string;
}

const Ctx = createContext<I18n | null>(null);

function initialLang(): Lang {
  try {
    const stored = localStorage.getItem("tptfx-lang");
    if (stored === "de" || stored === "en") return stored;
  } catch {
    // storage blocked
  }
  return navigator.language?.toLowerCase().startsWith("de") ? "de" : "en";
}

export function I18nProvider({ children, lang: forced }: { children: ReactNode; lang?: Lang }) {
  const [lang, setLangState] = useState<Lang>(forced ?? initialLang);
  useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);
  const setLang = useCallback((l: Lang) => {
    setLangState(l);
    try {
      localStorage.setItem("tptfx-lang", l);
    } catch {
      // storage blocked
    }
  }, []);
  const value = useMemo<I18n>(
    () => ({
      lang,
      setLang,
      t: (key, vars) => {
        let s = MESSAGES[lang][key] ?? key;
        if (vars) for (const [k, v] of Object.entries(vars)) s = s.replace(`{${k}}`, String(v));
        return s;
      },
    }),
    [lang, setLang],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useI18n(): I18n {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useI18n outside I18nProvider");
  return ctx;
}
