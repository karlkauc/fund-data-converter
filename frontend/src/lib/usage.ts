/**
 * What the visitor does with a result – download it, hand it over – for the usage statistics
 * (backend/app/api/usage.py). The server cannot see either. Only fixed values are sent, never the
 * file or its name; a failure is ignored.
 */
import type { Direction } from "../types";

export interface UsageEvent {
  type: "download" | "handoff";
  /** download: the file type; handoff: the site. */
  target: "xml" | "xlsx" | "csv" | "zip" | "validator" | "xml-viewer";
  direction?: Direction;
  outcome?: "ok" | "timeout" | "blocked";
}

/** The file type of a download, from its name (a zipped result counts as zip). */
export function fileType(filename: string): UsageEvent["target"] {
  const ext = filename.toLowerCase().split(".").pop() ?? "";
  return ext === "xml" || ext === "csv" || ext === "zip" ? ext : "xlsx";
}

export function reportUsage(event: UsageEvent): void {
  try {
    // keepalive: the request survives a download or a tab switch right after the click.
    void fetch("/api/usage/event", {
      method: "POST",
      keepalive: true,
      headers: { "Content-Type": "application/json", "X-Client": "web" },
      body: JSON.stringify(event),
    }).catch(() => undefined);
  } catch {
    /* statistics never get in the way */
  }
}
