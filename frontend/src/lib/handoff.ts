/**
 * Hand a converted file over to a sibling site: FundsXML to xml-viewer.online, TPT to
 * findatex-validator.eu.
 *
 * We open `<site>/?from=tpt-converter` in a new tab and keep the bytes in memory. The new tab
 * posts `{type: "<site>:ready"}` back once it has mounted; we answer with
 * `{type: "<site>:file", name, content, …}` and transfer the ArrayBuffer. The file goes from this
 * tab to the other one and is never stored on the way. Origins are checked on both sides: the
 * sites post their ready message only to the origins in their allow-lists (`SENDER_ORIGINS` in
 * their lib/handoff.ts), so from any other host the hand-over can never complete.
 *
 * This only works while we send no `Cross-Origin-Opener-Policy: same-origin` (the popup would
 * lose its opener).
 */

export const HANDOFF_TIMEOUT_MS = 15_000;
const SOURCE = "tpt-converter";

/** Origins the sibling sites accept a hand-over from; keep in step with their allow-lists. */
// The old address stays until the sibling sites and every open tab have moved on.
export const SENDER_ORIGINS = ["https://www.fund-data-converter.eu", "https://converter.status20.net"];

const DEV_ORIGIN = /^http:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/;

export interface HandoffTarget {
  url: string;
  origins: string[];
  /** Message type prefix: `<prefix>:ready`, `<prefix>:file`. */
  prefix: string;
}

/** Development only: point the buttons at local instances of the sibling sites. */
function devUrl(value: string | undefined, fallback: string): string {
  return import.meta.env.DEV && value ? value : fallback;
}

export const XML_VIEWER: HandoffTarget = {
  url: devUrl(import.meta.env.VITE_XML_VIEWER_URL, "https://www.xml-viewer.online/"),
  origins: ["https://www.xml-viewer.online", "https://xml-viewer.online"],
  prefix: "xml-viewer",
};

export const FINDATEX_VALIDATOR: HandoffTarget = {
  url: devUrl(import.meta.env.VITE_FINDATEX_VALIDATOR_URL, "https://www.findatex-validator.eu/"),
  origins: ["https://www.findatex-validator.eu", "https://findatex-validator.eu"],
  prefix: "findatex-validator",
};

export function handoffSupported(origin: string = window.location.origin): boolean {
  return SENDER_ORIGINS.includes(origin) || (import.meta.env.DEV && DEV_ORIGIN.test(origin));
}

export function handoffUrl(target: HandoffTarget): string {
  const url = new URL(target.url);
  url.searchParams.set("from", SOURCE);
  url.searchParams.set("utm_source", SOURCE);
  url.searchParams.set("utm_medium", "handoff");
  return url.toString();
}

function isTargetOrigin(target: HandoffTarget, origin: string): boolean {
  return target.origins.includes(origin) || (import.meta.env.DEV && DEV_ORIGIN.test(origin));
}

/** The schema sent along to the XML viewer: a ZIP of every file, with its root schema. */
export interface HandoffSchema {
  name: string;
  content: ArrayBuffer;
  mainFilename?: string;
}

export async function fetchFundsXmlSchema(): Promise<HandoffSchema> {
  const res = await fetch("/api/schema/fundsxml.zip");
  if (!res.ok) throw new Error(`schema: HTTP ${res.status}`);
  return { name: "FundsXML.zip", content: await res.arrayBuffer(), mainFilename: "FundsXML4.xsd" };
}

export interface HandoffOptions {
  /** Fields added to the file message, e.g. templateId / templateVersion for the validator. */
  extra?: Record<string, string>;
  /** Fetched while the popup loads; a failure just means the file travels alone. */
  schema?: () => Promise<HandoffSchema>;
  timeoutMs?: number;
  /** Overrides the target URL (tests, local development). */
  url?: string;
}

/**
 * Open `target` and post the file once it reports ready. Call it straight from a click handler:
 * the popup is opened synchronously, before anything is awaited, so it is not blocked.
 * Resolves `true` when the file was posted, `false` when the popup was blocked or never answered
 * (the tab stays open; the visitor can upload by hand).
 */
export function handOff(
  target: HandoffTarget,
  name: string,
  content: ArrayBuffer,
  opts: HandoffOptions = {},
): Promise<boolean> {
  const url = opts.url ?? handoffUrl(target);
  const popup = window.open(url, "_blank");
  if (!popup) return Promise.resolve(false);
  const targetOrigin = new URL(url).origin;
  const schemaPromise: Promise<HandoffSchema | undefined> = opts.schema
    ? opts.schema().catch(() => undefined)
    : Promise.resolve(undefined);

  return new Promise<boolean>((resolve) => {
    let answered = false;
    const finish = (ok: boolean) => {
      window.removeEventListener("message", onMessage);
      window.clearTimeout(timer);
      resolve(ok);
    };
    const onMessage = (event: MessageEvent) => {
      if (answered || event.source !== popup || !isTargetOrigin(target, event.origin)) return;
      const data = event.data as { type?: unknown } | null;
      if (!data || data.type !== `${target.prefix}:ready`) return;
      answered = true;
      void schemaPromise.then((schema) => {
        const message: Record<string, unknown> = { type: `${target.prefix}:file`, name, content, ...opts.extra };
        const transfer: Transferable[] = [content];
        if (schema) {
          message.schema = schema;
          transfer.push(schema.content);
        }
        popup.postMessage(message, targetOrigin, transfer);
        finish(true);
      });
    };
    window.addEventListener("message", onMessage);
    const timer = window.setTimeout(() => finish(false), opts.timeoutMs ?? HANDOFF_TIMEOUT_MS);
  });
}
