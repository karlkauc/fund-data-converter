import type {
  ConvertOptions,
  ConvertResult,
  FaqEntry,
  Format,
  MappingField,
  OpenfundsMappingField,
  RateWindow,
} from "../types";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

async function errorFrom(res: Response): Promise<ApiError> {
  let detail = res.statusText;
  try {
    const body = await res.json();
    if (typeof body?.detail === "string") detail = body.detail;
  } catch {
    // not JSON
  }
  return new ApiError(detail, res.status);
}

/** ``target``: the format wanted; the server detects the format of the file itself. */
export async function convertFile(
  file: File,
  opts: ConvertOptions,
  target: Format,
  signal?: AbortSignal,
): Promise<ConvertResult> {
  const form = new FormData();
  form.append("file", file, file.name);
  form.append("target", target);
  if (opts.tptVersion) form.append("tpt_version", opts.tptVersion);
  form.append("include_block", String(opts.includeBlock));
  form.append("include_core", String(opts.includeCore));
  form.append("output_format", opts.outputFormat);
  form.append("delimiter", opts.delimiter);
  if (target === "openfunds") {
    form.append("of_header_names", String(opts.ofHeaderNames));
    form.append("non_openfunds_columns", String(opts.nonOpenfundsColumns));
  }
  // X-Client tells the usage statistics the SPA from API scripts (backend/app/main.py).
  const res = await fetch("/api/convert", { method: "POST", body: form, headers: { "X-Client": "web" }, signal });
  if (!res.ok) throw await errorFrom(res);
  return res.json();
}

/** The caller's rate limit for /api/convert; asking does not count as a conversion. */
export async function fetchLimits(): Promise<RateWindow[]> {
  const res = await fetch("/api/limits");
  if (!res.ok) throw await errorFrom(res);
  const body = await res.json();
  return Array.isArray(body?.convert) ? body.convert : [];
}

// Keep in sync with SAMPLES in backend/app/api/samples.py (titles and descriptions: SAMPLE_TEXT in i18n.tsx).
export const SAMPLE_FILES = {
  "tpt-v7": "tpt_v7_sample.xlsx",
  "tpt-v8": "tpt_v8_sample.xlsx",
  "tpt-all-cic": "tpt_all_cic.xlsx",
  "tpt-multi": "tpt_multi_fund.xlsx",
  "tpt-csv": "tpt_semicolon.csv",
  "tpt-errors": "tpt_with_errors.xlsx",
  fundsxml: "fundsxml_sample.xml",
  "fundsxml-all-cic": "fundsxml_all_cic.xml",
  "fundsxml-core-only": "fundsxml_core_only.xml",
  "fundsxml-fund-portfolio": "fundsxml_fund_portfolio.xml",
  "fundsxml-openfunds": "fundsxml_from_openfunds.xml",
  "fundsxml-errors": "fundsxml_with_errors.xml",
  openfunds: "openfunds_sample.xlsx",
  "openfunds-multi": "openfunds_multi.xlsx",
  "openfunds-static": "openfunds_static.xlsx",
  "openfunds-zip": "openfunds_csv.zip",
  "openfunds-errors": "openfunds_with_errors.xlsx",
} as const;

export type SampleName = keyof typeof SAMPLE_FILES;

/** The samples of a source format, in the order shown ("-errors" ones carry delivery errors). */
export function samplesOf(format: Format): SampleName[] {
  return (Object.keys(SAMPLE_FILES) as SampleName[]).filter((n) => n.split("-")[0] === format);
}

export function sampleUrl(name: SampleName, download = false): string {
  return `/api/samples/${name}${download ? "?download=1" : ""}`;
}

export async function fetchSample(name: SampleName): Promise<File> {
  const res = await fetch(sampleUrl(name));
  if (!res.ok) throw await errorFrom(res);
  const blob = await res.blob();
  return new File([blob], SAMPLE_FILES[name], { type: blob.type });
}

export interface FeedbackPayload {
  message: string;
  email?: string;
  page?: string;
  direction?: string;
  tpt_version?: string;
  error_detail?: string;
  website?: string; // honeypot
}

export async function sendFeedback(payload: FeedbackPayload): Promise<void> {
  const res = await fetch("/api/feedback", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw await errorFrom(res);
}

export async function fetchMapping(version: "V7" | "V8"): Promise<MappingField[]> {
  const res = await fetch(`/api/mapping/${version}`);
  if (!res.ok) throw await errorFrom(res);
  return (await res.json()).fields;
}

export async function fetchOpenfundsMapping(): Promise<{ version: string; fields: OpenfundsMappingField[] }> {
  const res = await fetch("/api/mapping/openfunds");
  if (!res.ok) throw await errorFrom(res);
  return res.json();
}

export async function fetchFaq(): Promise<FaqEntry[]> {
  const res = await fetch("/api/content/faq");
  if (!res.ok) throw await errorFrom(res);
  return res.json();
}
