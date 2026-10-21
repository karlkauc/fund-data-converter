import type { ConvertOptions, ConvertResult, FaqEntry, MappingField } from "../types";

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

export async function convertFile(file: File, opts: ConvertOptions, signal?: AbortSignal): Promise<ConvertResult> {
  const form = new FormData();
  form.append("file", file, file.name);
  if (opts.tptVersion) form.append("tpt_version", opts.tptVersion);
  form.append("include_block", String(opts.includeBlock));
  form.append("include_core", String(opts.includeCore));
  form.append("output_format", opts.outputFormat);
  form.append("delimiter", opts.delimiter);
  // X-Client tells the usage statistics the SPA from API scripts (backend/app/main.py).
  const res = await fetch("/api/convert", { method: "POST", body: form, headers: { "X-Client": "web" }, signal });
  if (!res.ok) throw await errorFrom(res);
  return res.json();
}

export async function fetchSample(name: "tpt-v7" | "tpt-v8" | "fundsxml"): Promise<File> {
  const res = await fetch(`/api/samples/${name}`);
  if (!res.ok) throw await errorFrom(res);
  const blob = await res.blob();
  const filename =
    name === "fundsxml" ? "fundsxml_sample.xml" : name === "tpt-v8" ? "tpt_v8_sample.xlsx" : "tpt_v7_sample.xlsx";
  return new File([blob], filename, { type: blob.type });
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

export async function fetchFaq(): Promise<FaqEntry[]> {
  const res = await fetch("/api/content/faq");
  if (!res.ok) throw await errorFrom(res);
  return res.json();
}
