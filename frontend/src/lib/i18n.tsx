import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

export type Lang = "de" | "en";

const en = {
  appTitle: "TPT ⇄ FundsXML Converter",
  tagline: "Convert between TPT (V7/V8), FundsXML 4 and openfunds – in every direction.",
  privacy: "Files are processed in memory only and never stored. No login.",
  dirToFundsxml: "TPT → FundsXML",
  dirToTpt: "FundsXML → TPT",
  from: "From",
  to: "To",
  mapping: "Field mapping",
  api: "API",
  dropTitle: "Drop a file here or",
  chooseFile: "Choose file…",
  dropHintTpt: ".xlsx · .csv · .txt (TPT V7 or V8, max. 25 MB)",
  dropHintXml: ".xml (FundsXML 4, max. 25 MB)",
  dropHintOpenfunds: ".xlsx · .csv · .zip (openfunds with OF-ID columns, max. 25 MB)",
  trySample: "No file at hand? Try an example:",
  sampleV7: "TPT V7",
  sampleV8: "TPT V8",
  sampleXml: "FundsXML",
  sampleOpenfunds: "openfunds",
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
  openfundsOutput: "openfunds output",
  ofHeaderNames: "Second header row with the field names",
  nonOpenfundsColumns: "Keep TPT fields without an openfunds column (as columns TPT_<field>)",
  converting: "Converting…",
  newFile: "New file",
  detected: "detected",
  via: "via",
  overview: "Overview",
  portfolios: "Portfolios",
  funds: "Funds",
  shareclasses: "Share classes",
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
  hopStep: "FundsXML step",
  showErrors: "show",
  hideErrors: "hide",
  sourceBlock: "read from the TPT block",
  sourceCore: "read from the core structures",
  sourceBoth: "read from the TPT block and custom attributes",
  error: "Conversion failed",
  retry: "Try again",
  mappingTitle: "TPT and openfunds ⇄ FundsXML field mapping",
  mappingIntro:
    "Every TPT field and where it goes in FundsXML 4.2.11. Fields without a FundsXML element are kept as custom attributes (TPT_<field>) on the position, so the reverse conversion restores them.",
  ofMappingIntro:
    "Every openfunds {version} field and where it goes in FundsXML 4.2.11: the core structures, the EMT/EPT/EET/EFT template blocks or – for holdings – the TPT position fields. Fields without a FundsXML element are kept as custom attributes (OF_<OF-ID>) on the share class or position, so the reverse conversion restores them.",
  statusTemplate: "template block",
  statusHolding: "holding (TPT field)",
  colLevel: "Level",
  colTarget: "FundsXML target",
  allAreas: "All areas",
  moreRows: "Show {n} more",
  search: "Search field, name or path…",
  statusBoth: "block + core",
  statusBlock: "block only",
  statusCore: "core only",
  statusCustom: "custom attribute",
  colField: "Field",
  colBlock: "TPT block",
  colCore: "Core structures",
  when: "when",
  footer: "Free · no account · no cookies · files are not stored · anonymous usage statistics",
  guides: "Guides",
  allFields: "All TPT fields",
  allOpenfundsFields: "All openfunds fields",
  messages: "Conversion messages",
  family: "Part of the FreeXmlToolkit family:",
  desktopApp: "Desktop app",
  faqTitle: "Frequently asked questions",
  feedback: "Feedback",
  reportProblem: "Report a problem",
  feedbackTitle: "Send feedback",
  feedbackIntro: "A bug, a field that ends up in the wrong place, a missing feature – anything helps.",
  feedbackMessage: "Your message",
  feedbackPlaceholder: "What happened, or what would you like to see?",
  feedbackEmail: "Email (optional, only if you want a reply)",
  feedbackErrorAttached: "Error attached",
  feedbackPrivacy: "Stored without your IP address; your file is never sent.",
  feedbackSend: "Send",
  feedbackSending: "Sending…",
  feedbackSent: "Thanks – your feedback was sent.",
  feedbackFailed: "Could not send",
  feedbackClose: "Close",
  backToConverter: "Back to the converter",
  theme: "Switch theme",
  language: "Deutsch",
};

const de: typeof en = {
  appTitle: "TPT ⇄ FundsXML Converter",
  tagline: "Konvertiere zwischen TPT (V7/V8), FundsXML 4 und openfunds – in jede Richtung.",
  privacy: "Dateien werden nur im Speicher verarbeitet und nicht gespeichert. Kein Login.",
  dirToFundsxml: "TPT → FundsXML",
  dirToTpt: "FundsXML → TPT",
  from: "Von",
  to: "Nach",
  mapping: "Feld-Mapping",
  api: "API",
  dropTitle: "Datei hierher ziehen oder",
  chooseFile: "Datei wählen…",
  dropHintTpt: ".xlsx · .csv · .txt (TPT V7 oder V8, max. 25 MB)",
  dropHintXml: ".xml (FundsXML 4, max. 25 MB)",
  dropHintOpenfunds: ".xlsx · .csv · .zip (openfunds mit OF-ID-Spalten, max. 25 MB)",
  trySample: "Keine Datei zur Hand? Beispiel laden:",
  sampleV7: "TPT V7",
  sampleV8: "TPT V8",
  sampleXml: "FundsXML",
  sampleOpenfunds: "openfunds",
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
  openfundsOutput: "openfunds-Ausgabe",
  ofHeaderNames: "Zweite Kopfzeile mit den Feldnamen",
  nonOpenfundsColumns: "TPT-Felder ohne openfunds-Spalte behalten (als Spalten TPT_<Feld>)",
  converting: "Konvertiere…",
  newFile: "Neue Datei",
  detected: "erkannt",
  via: "über",
  overview: "Übersicht",
  portfolios: "Portfolios",
  funds: "Fonds",
  shareclasses: "Anteilsklassen",
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
  hopStep: "Zwischenschritt FundsXML",
  showErrors: "anzeigen",
  hideErrors: "ausblenden",
  sourceBlock: "aus dem TPT-Block gelesen",
  sourceCore: "aus den Core-Strukturen gelesen",
  sourceBoth: "aus TPT-Block und CustomAttributes gelesen",
  error: "Konvertierung fehlgeschlagen",
  retry: "Erneut versuchen",
  mappingTitle: "Feld-Mapping TPT und openfunds ⇄ FundsXML",
  mappingIntro:
    "Jedes TPT-Feld und sein Ziel in FundsXML 4.2.11. Felder ohne FundsXML-Element werden als CustomAttributes (TPT_<Feld>) an der Position abgelegt, damit die Rückkonvertierung sie wiederherstellt.",
  ofMappingIntro:
    "Jedes openfunds-{version}-Feld und sein Ziel in FundsXML 4.2.11: die Core-Strukturen, die Template-Blöcke EMT/EPT/EET/EFT oder – bei Holdings – die TPT-Positionsfelder. Felder ohne FundsXML-Element werden als CustomAttributes (OF_<OF-ID>) an der Anteilsklasse oder Position abgelegt, damit die Rückkonvertierung sie wiederherstellt.",
  statusTemplate: "Template-Block",
  statusHolding: "Holding (TPT-Feld)",
  colLevel: "Ebene",
  colTarget: "FundsXML-Ziel",
  allAreas: "Alle Bereiche",
  moreRows: "{n} weitere anzeigen",
  search: "Feld, Name oder Pfad suchen…",
  statusBoth: "Block + Core",
  statusBlock: "nur Block",
  statusCore: "nur Core",
  statusCustom: "CustomAttribute",
  colField: "Feld",
  colBlock: "TPT-Block",
  colCore: "Core-Strukturen",
  when: "wenn",
  footer: "Kostenlos · kein Konto · keine Cookies · Dateien werden nicht gespeichert · anonyme Nutzungsstatistik",
  guides: "Anleitungen (EN)",
  allFields: "Alle TPT-Felder (EN)",
  allOpenfundsFields: "Alle openfunds-Felder (EN)",
  messages: "Konvertierungsmeldungen (EN)",
  family: "Teil der FreeXmlToolkit-Familie:",
  desktopApp: "Desktop-App",
  faqTitle: "Häufige Fragen (EN)",
  feedback: "Feedback",
  reportProblem: "Problem melden",
  feedbackTitle: "Feedback senden",
  feedbackIntro: "Ein Fehler, ein Feld am falschen Platz, eine fehlende Funktion – alles hilft.",
  feedbackMessage: "Deine Nachricht",
  feedbackPlaceholder: "Was ist passiert, oder was würdest du dir wünschen?",
  feedbackEmail: "E-Mail (optional, nur wenn du eine Antwort möchtest)",
  feedbackErrorAttached: "Angehängter Fehler",
  feedbackPrivacy: "Gespeichert ohne IP-Adresse; deine Datei wird nie mitgeschickt.",
  feedbackSend: "Senden",
  feedbackSending: "Sende…",
  feedbackSent: "Danke – dein Feedback wurde gesendet.",
  feedbackFailed: "Senden fehlgeschlagen",
  feedbackClose: "Schließen",
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
    shareclass_no_portfolio: "Share class {shareclass} has no portfolio (neither its own nor the fund's); skipped.",
    shareclass_inactive: "Share class {shareclass} has no net assets on {date}; skipped.",
    fx_derived:
      "Portfolio {portfolio}: market values in {ccy} (24) of {n} position(s) converted from {fund_ccy} at the rate of the share class NAV.",
    fx_missing:
      "Portfolio {portfolio}: {n} position(s) have no market value in {ccy} (24), and the share class NAV gives no rate from {fund_ccy}.",
    more_messages: "… {n} more message(s) of this kind",
    of_unknown_field: "{n} OF-ID(s) are not in openfunds {version}; they are kept as is: {columns}",
    of_revoked_field: "{n} field(s) are revoked in openfunds {version}: {columns}",
    of_non_openfunds_column: "{n} column(s) are not openfunds fields; they are kept under their header name: {columns}",
    of_ignore_value: "{n} value(s) are [IGNORE] and were treated as not delivered.",
    of_value_conflict: "{key}: {field} is given twice ({first} and {second}); the first one is used.",
    of_value_invalid: "{field} ({name}) = {value} is not {expected}.",
    of_holding_unassigned:
      "{n} holding(s) name no share class of the file (OFST020000) and the file has several share classes; they were not converted.",
    of_fund_value_differs: "{field} differs from the fund's first share class; kept as custom attribute of the share class.",
    of_template_incomplete: "The {template} data lacks mandatory fields ({missing}); its values are kept as custom attributes.",
    of_template_rejected: "Not accepted by the template block – kept as custom attribute",
    of_value_lost: "Lost: not accepted as custom attribute either",
    of_subfunds_skipped: "Umbrella structures (Fund/Subfunds) are not read; only single funds and their share classes.",
    no_shareclasses: "The document contains neither funds nor positions.",
    hop_data_loss: "{n} {source} field(s) have no place in {target} and are not in the output: {columns}",
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
    shareclass_no_portfolio: "Anteilsklasse {shareclass} hat kein Portfolio (weder ein eigenes noch das des Fonds); übersprungen.",
    shareclass_inactive: "Anteilsklasse {shareclass} hat am {date} kein Nettovermögen; übersprungen.",
    fx_derived:
      "Portfolio {portfolio}: Marktwerte in {ccy} (24) von {n} Position(en) aus {fund_ccy} zum Kurs des Anteilsklassen-NAV umgerechnet.",
    fx_missing:
      "Portfolio {portfolio}: {n} Position(en) haben keinen Marktwert in {ccy} (24), und der Anteilsklassen-NAV liefert keinen Kurs aus {fund_ccy}.",
    more_messages: "… {n} weitere Hinweis(e) dieser Art",
    of_unknown_field: "{n} OF-ID(s) gibt es in openfunds {version} nicht; sie bleiben unverändert erhalten: {columns}",
    of_revoked_field: "{n} Feld(er) sind in openfunds {version} zurückgezogen: {columns}",
    of_non_openfunds_column: "{n} Spalte(n) sind keine openfunds-Felder; sie bleiben unter ihrem Spaltennamen erhalten: {columns}",
    of_ignore_value: "{n} Wert(e) sind [IGNORE] und wurden als nicht geliefert behandelt.",
    of_value_conflict: "{key}: {field} ist doppelt angegeben ({first} und {second}); der erste Wert wird verwendet.",
    of_value_invalid: "{field} ({name}) = {value} ist nicht {expected}.",
    of_holding_unassigned:
      "{n} Holding(s) nennen keine Anteilsklasse der Datei (OFST020000), und die Datei hat mehrere Anteilsklassen; sie wurden nicht konvertiert.",
    of_fund_value_differs: "{field} weicht von der ersten Anteilsklasse des Fonds ab; als CustomAttribute der Anteilsklasse erhalten.",
    of_template_incomplete: "Den {template}-Daten fehlen Pflichtfelder ({missing}); ihre Werte bleiben als CustomAttributes erhalten.",
    of_template_rejected: "Vom Template-Block nicht übernommen – als CustomAttribute erhalten",
    of_value_lost: "Verloren: auch als CustomAttribute nicht angenommen",
    of_subfunds_skipped: "Umbrella-Strukturen (Fund/Subfunds) werden nicht gelesen; nur Einzelfonds und ihre Anteilsklassen.",
    no_shareclasses: "Das Dokument enthält weder Fonds noch Positionen.",
    hop_data_loss: "{n} {source}-Feld(er) haben in {target} keinen Platz und fehlen in der Ausgabe: {columns}",
  },
};

/** Every issue code with a text, for the API documentation. */
export const ISSUE_CODES = Object.keys(ISSUES.en);

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
