import type { ConvertOptions, ConvertResult, FaqEntry, Format, MappingField, OpenfundsMappingField } from "../types";

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

export type SampleName = "tpt-v7" | "tpt-v8" | "fundsxml" | "openfunds";

// Keep in sync with SAMPLES in backend/app/api/samples.py.
const SAMPLE_FILES: Record<SampleName, string> = {
  "tpt-v7": "tpt_v7_sample.xlsx",
  "tpt-v8": "tpt_v8_sample.xlsx",
  fundsxml: "fundsxml_sample.xml",
  openfunds: "openfunds_sample.xlsx",
};

export async function fetchSample(name: SampleName): Promise<File> {
  const res = await fetch(`/api/samples/${name}`);
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
