import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, vi } from "vitest";
import { Converter } from "../src/components/Converter";
import { FINDATEX_VALIDATOR, XML_VIEWER, handOff, handoffSupported, handoffUrl } from "../src/lib/handoff";
import { I18nProvider } from "../src/lib/i18n";

const VIEWER = "https://www.xml-viewer.online";

function fakePopup() {
  return { postMessage: vi.fn() };
}

function ready(popup: unknown, type: string, origin: string) {
  window.dispatchEvent(new MessageEvent("message", { data: { type }, origin, source: popup as Window }));
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

test("the target URL names the converter as source", () => {
  const url = new URL(handoffUrl(FINDATEX_VALIDATOR));
  expect(url.origin).toBe("https://www.findatex-validator.eu");
  expect(url.searchParams.get("from")).toBe("tpt-converter");
  expect(url.searchParams.get("utm_source")).toBe("tpt-converter");
});

test("hand-over is offered only where the sibling sites accept it", () => {
  expect(handoffSupported("https://www.fund-data-converter.eu")).toBe(true);
  expect(handoffSupported("https://converter.status20.net")).toBe(true);
  expect(handoffSupported("https://evil.example")).toBe(false);
  // Vitest runs in dev mode, like the Vite dev server.
  expect(handoffSupported("http://localhost:5173")).toBe(true);
});

test("the file and extra fields are posted after the ready message", async () => {
  const popup = fakePopup();
  vi.spyOn(window, "open").mockReturnValue(popup as unknown as Window);
  const content = new Uint8Array([1, 2, 3]).buffer;
  const sent = handOff(FINDATEX_VALIDATOR, "a_TPT_V7.xlsx", content, {
    extra: { templateId: "TPT", templateVersion: "V7.0" },
  });
  // Wrong origin and wrong window are ignored.
  ready(popup, "findatex-validator:ready", "https://evil.example");
  ready({}, "findatex-validator:ready", "https://www.findatex-validator.eu");
  expect(popup.postMessage).not.toHaveBeenCalled();
  ready(popup, "findatex-validator:ready", "https://www.findatex-validator.eu");
  await expect(sent).resolves.toBe("ok");
  expect(popup.postMessage).toHaveBeenCalledWith(
    { type: "findatex-validator:file", name: "a_TPT_V7.xlsx", content, templateId: "TPT", templateVersion: "V7.0" },
    "https://www.findatex-validator.eu",
    [content],
  );
});

test("the schema travels along to the XML viewer", async () => {
  const popup = fakePopup();
  vi.spyOn(window, "open").mockReturnValue(popup as unknown as Window);
  const schema = { name: "FundsXML.zip", content: new ArrayBuffer(4), mainFilename: "FundsXML4.xsd" };
  const content = new ArrayBuffer(2);
  const sent = handOff(XML_VIEWER, "a.xml", content, { schema: async () => schema });
  ready(popup, "xml-viewer:ready", VIEWER);
  await expect(sent).resolves.toBe("ok");
  const [message, origin, transfer] = popup.postMessage.mock.calls[0];
  expect(message).toMatchObject({ type: "xml-viewer:file", name: "a.xml", schema });
  expect(origin).toBe(VIEWER);
  expect(transfer).toEqual([content, schema.content]);
});

test("a blocked popup and a silent tab say which it was", async () => {
  vi.spyOn(window, "open").mockReturnValue(null);
  await expect(handOff(XML_VIEWER, "a.xml", new ArrayBuffer(1))).resolves.toBe("blocked");
  vi.useFakeTimers();
  vi.spyOn(window, "open").mockReturnValue(fakePopup() as unknown as Window);
  const sent = handOff(XML_VIEWER, "a.xml", new ArrayBuffer(1), { timeoutMs: 1000 });
  vi.advanceTimersByTime(1000);
  await expect(sent).resolves.toBe("timeout");
});

describe("buttons in the result view", () => {
  const base = {
    input: { filename: "a.csv", kind: "tpt", format: "csv", delimiter: ";", version: "V7", versionSource: "field 1000", columns: 3 },
    summary: { portfolios: 1, positions: 0, assets: 0, portfolioList: [] },
    coverage: { present: 0, block: 0, core: 0, custom: 0, fields: [] },
    issues: [],
    preview: { columns: [], rows: [], total: 0 },
  };
  const toFundsXml = {
    ...base,
    direction: "tpt-to-fundsxml",
    validation: { valid: true, errors: [] },
    xmlPreview: "<FundsXML4/>",
    output: { filename: "a_FundsXML.xml", mimeType: "application/xml", size: 12, zipped: false, base64: "PEZ1bmRzWE1MNC8+" },
  };

  beforeEach(() => {
    window.history.replaceState(null, "", "/");
  });

  async function convert(result: object, direction: string) {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => result }));
    render(
      <I18nProvider lang="en">
        <Converter direction={direction as "tpt-to-fundsxml"} />
      </I18nProvider>,
    );
    fireEvent.change(screen.getByTestId("file-input"), { target: { files: [new File(["x"], "a.csv")] } });
    await waitFor(() => expect(screen.getByText(/Download/)).toBeInTheDocument());
  }

  test("FundsXML output offers the XML viewer", async () => {
    await convert(toFundsXml, "tpt-to-fundsxml");
    const popup = fakePopup();
    const open = vi.spyOn(window, "open").mockReturnValue(popup as unknown as Window);
    fireEvent.click(screen.getByRole("button", { name: /Open in xml-viewer.online/ }));
    expect(open.mock.calls[0][0]).toContain("https://www.xml-viewer.online/?from=tpt-converter");
    expect(screen.queryByRole("button", { name: /findatex-validator/ })).toBeNull();
  });

  test("TPT output offers the validator with its version", async () => {
    await convert(
      {
        ...base,
        direction: "fundsxml-to-tpt",
        input: { filename: "a.xml", kind: "fundsxml", version: "V8", source: "core" },
        output: { filename: "a_TPT_V8.xlsx", mimeType: "application/xlsx", size: 3, zipped: false, base64: "AAEC" },
      },
      "fundsxml-to-tpt",
    );
    const popup = fakePopup();
    vi.spyOn(window, "open").mockReturnValue(popup as unknown as Window);
    fireEvent.click(screen.getByRole("button", { name: /Check in findatex-validator.eu/ }));
    ready(popup, "findatex-validator:ready", "https://www.findatex-validator.eu");
    await waitFor(() => expect(popup.postMessage).toHaveBeenCalled());
    expect(popup.postMessage.mock.calls[0][0]).toMatchObject({ templateId: "TPT", templateVersion: "V8.0" });
  });

  test("zipped output is not handed over", async () => {
    await convert({ ...toFundsXml, output: { ...toFundsXml.output, zipped: true } }, "tpt-to-fundsxml");
    expect(screen.queryByRole("button", { name: /xml-viewer/ })).toBeNull();
    expect(screen.getByText(/delivered as a ZIP/)).toBeInTheDocument();
  });
});
