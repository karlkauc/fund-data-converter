// Mirrors the JSON built in backend/app/service.py (keep in sync by hand).

export type Direction = "tpt-to-fundsxml" | "fundsxml-to-tpt";

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
    kind: "tpt" | "fundsxml";
    format?: string;
    delimiter?: string | null;
    version: string;
    versionSource?: string;
    columns?: number;
    unmappedColumns?: string[];
    source?: string;
  };
  summary: {
    portfolios: number;
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
  output: { filename: string; mimeType: string; size: number; base64: string };
}

export interface ConvertOptions {
  tptVersion: "" | "V7" | "V8";
  includeBlock: boolean;
  includeCore: boolean;
  outputFormat: "xlsx" | "csv";
  delimiter: "semicolon" | "comma" | "pipe" | "tab";
}

export interface MappingRule {
  path: string;
  when?: string;
  transform?: string;
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
