// Mirrors the JSON built in backend/app/service.py (keep in sync by hand).

export type Format = "tpt" | "fundsxml" | "openfunds";
export type Direction =
  | "tpt-to-fundsxml"
  | "fundsxml-to-tpt"
  | "openfunds-to-fundsxml"
  | "fundsxml-to-openfunds"
  | "tpt-to-openfunds"
  | "openfunds-to-tpt";

export interface Issue {
  level: "error" | "warning" | "info";
  code: string;
  message: string;
  field?: string;
  row?: number;
  path?: string;
  value?: string;
  detail?: string;
  params?: Record<string, string | number>;
  /** Set for issues of the intermediate FundsXML step of TPT ⇄ openfunds. */
  hop?: "fundsxml";
}

export interface PortfolioSummary {
  id: string;
  date: string;
  name: string;
  currency: string;
  nav: string;
  positions: number;
}

export interface CoverageField {
  key: string;
  name: string;
  block: boolean;
  core: boolean;
  custom: boolean;
}

export interface ConvertResult {
  direction: Direction;
  input: {
    filename: string;
    kind: Format;
    format?: string;
    delimiter?: string | null;
    /** TPT version (TPT input, or FundsXML → TPT output) or openfunds version (openfunds input). */
    version?: string;
    /** Version written when the output is TPT or openfunds and the input is not FundsXML. */
    outputVersion?: string;
    versionSource?: string;
    layout?: "flat" | "narrow";
    columns?: number;
    unmappedColumns?: string[];
    source?: string;
  };
  summary: {
    portfolios?: number;
    funds?: number;
    shareclasses?: number;
    positions: number;
    assets?: number;
    custom_attributes?: number;
    source?: string;
    portfolioList: PortfolioSummary[];
  };
  coverage: {
    present: number;
    block: number;
    core: number;
    custom: number;
    total?: number;
    fields: CoverageField[];
  };
  issues: Issue[];
  validation: { valid: boolean | null; errors: string[] } | null;
  preview: { columns: { key: string; name: string }[]; rows: string[][]; total: number };
  xmlPreview: string | null;
  xmlPreviewTruncated?: boolean;
  output: { filename: string; mimeType: string; size: number; zipped: boolean; sha256: string; base64: string };
  issueCounts: { error: number; warning: number; info: number };
  /** Values that did not reach the output where they belong (counted before capping); null if not tracked. */
  dataLoss: { lost: number; keptAsCustomAttribute: number; notInCoreStructures: number; codes: string[] } | null;
  meta: {
    converterVersion: string;
    fundsxmlSchema: string;
    input: { bytes: number; sha256: string };
    durationMs: number;
  };
  /** The caller's rate limit after this conversion (Quota.status in backend/app/rate_limit.py). */
  rateLimit?: RateWindow[];
}

/** One window of the /api/convert rate limit; resetSeconds is 0 while the window has not started. */
export interface RateWindow {
  window: string;
  limit: number;
  remaining: number;
  resetSeconds: number;
}

export interface ConvertOptions {
  tptVersion: "" | "V7" | "V8";
  includeBlock: boolean;
  includeCore: boolean;
  outputFormat: "xlsx" | "csv";
  delimiter: "semicolon" | "comma" | "pipe" | "tab";
  /** openfunds output: a second header row with the field names. */
  ofHeaderNames: boolean;
  /** TPT → openfunds: TPT fields without an openfunds column as TPT_<field> columns. */
  nonOpenfundsColumns: boolean;
}

export interface MappingRule {
  path: string;
  when?: string;
  transform?: string;
}

/** GET /api/content/faq (backend/app/api/content.py). */
export interface FaqEntry {
  question: string;
  answer_html: string;
}

export interface MappingField {
  key: string;
  name: string;
  definition: string;
  flag: string;
  block: MappingRule[];
  core: MappingRule[];
  status: "block+core" | "block" | "core" | "custom";
}

/** GET /api/mapping/openfunds (backend/app/api/mapping.py). */
export interface OpenfundsMappingField {
  key: string;
  name: string;
  level: string;
  tags: string[];
  type: string;
  definition: string;
  core: MappingRule[];
  template: (MappingRule & { template: string })[];
  holding: string[];
  status: "core" | "template" | "holding" | "custom";
}
