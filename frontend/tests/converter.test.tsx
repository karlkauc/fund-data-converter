import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";
import { Converter } from "../src/components/Converter";
import { I18nProvider } from "../src/lib/i18n";

const RESULT = {
  direction: "tpt-to-fundsxml",
  input: { filename: "a.csv", kind: "tpt", format: "csv", delimiter: ";", version: "V7", versionSource: "field 1000", columns: 3 },
  summary: { portfolios: 1, positions: 2, assets: 2, portfolioList: [{ id: "FR1", date: "2025-12-31", name: "Fund", currency: "EUR", nav: "1", positions: 2 }] },
  coverage: { present: 3, block: 3, core: 2, custom: 0, fields: [] },
  issues: [{ level: "warning", code: "mandatory_missing", message: "m", params: { name: "5_NAV", n: 1 } }],
  validation: { valid: true, errors: [] },
  preview: { columns: [{ key: "1", name: "1_Portfolio" }], rows: [["FR1"], ["FR1"]], total: 2 },
  xmlPreview: '<FundsXML4 a="1"/>',
  output: { filename: "a_FundsXML.xml", mimeType: "application/xml", size: 12, base64: "PEZ1bmRzWE1MNC8+" },
};

test("uploading a file converts it and shows the result", async () => {
  const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => RESULT });
  vi.stubGlobal("fetch", fetchMock);
  render(
    <I18nProvider lang="en">
      <Converter direction="tpt-to-fundsxml" />
    </I18nProvider>,
  );
  const file = new File(["1;6;12\nFR1;2025-12-31;FR12"], "a.csv", { type: "text/csv" });
  fireEvent.change(screen.getByTestId("file-input"), { target: { files: [file] } });
  await waitFor(() => expect(screen.getByText(/valid against FundsXML/)).toBeInTheDocument());
  expect(screen.getByText("Mandatory field 5_NAV is empty in 1 row(s).")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "XML" }));
  const tag = screen.getByTestId("xml-preview").querySelector("span.text-blue-700");
  expect(tag).not.toBeNull();
  // The FAQ below the drop zone fetches /api/content/faq first.
  const [url, init] = fetchMock.mock.calls.find(([u]) => u === "/api/convert")!;
  expect(url).toBe("/api/convert");
  expect((init.body as FormData).get("include_core")).toBe("true");
  expect(init.headers).toEqual({ "X-Client": "web" });
});

test("an API error is shown", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 422, statusText: "x", json: async () => ({ detail: "no TPT header row found" }) }));
  render(
    <I18nProvider lang="en">
      <Converter direction="tpt-to-fundsxml" />
    </I18nProvider>,
  );
  fireEvent.change(screen.getByTestId("file-input"), { target: { files: [new File(["x"], "a.csv")] } });
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("no TPT header row found"));
});

test("example cards per source format load a sample and offer its download", async () => {
  const fetchMock = vi.fn(async (url: string, _init?: RequestInit) =>
    url.startsWith("/api/samples/")
      ? { ok: true, blob: async () => new Blob(["x"], { type: "application/xml" }) }
      : { ok: true, json: async () => (url === "/api/convert" ? RESULT : []) },
  );
  vi.stubGlobal("fetch", fetchMock);
  render(
    <I18nProvider lang="de">
      <Converter direction="fundsxml-to-tpt" />
    </I18nProvider>,
  );
  const cards = screen.getByTestId("samples");
  expect(cards.querySelectorAll("li")).toHaveLength(6);
  expect(screen.getByText("mit Fehlern")).toBeInTheDocument();
  const link = screen.getByRole("link", { name: "fundsxml_fund_portfolio.xml herunterladen" });
  expect(link).toHaveAttribute("href", "/api/samples/fundsxml-fund-portfolio?download=1");
  fireEvent.click(screen.getByRole("button", { name: /Fondsportfolio/ }));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/convert", expect.anything()));
  expect(fetchMock).toHaveBeenCalledWith("/api/samples/fundsxml-fund-portfolio");
  const init = fetchMock.mock.calls.find(([u]) => u === "/api/convert")![1]!;
  expect(((init.body as FormData).get("file") as File).name).toBe("fundsxml_fund_portfolio.xml");
});

const WINDOWS = (minute: number, hour: number, reset = 0) => [
  { window: "minute", limit: 20, remaining: minute, resetSeconds: reset },
  { window: "hour", limit: 200, remaining: hour, resetSeconds: reset ? 3000 : 0 },
];

function routedFetch(convert: () => unknown) {
  return vi.fn((url: string) => {
    if (url === "/api/limits") return Promise.resolve({ ok: true, json: async () => ({ convert: WINDOWS(20, 200) }) });
    if (url === "/api/convert") return Promise.resolve(convert());
    return Promise.resolve({ ok: true, json: async () => [] });
  });
}

test("the rate limit is shown and follows each conversion", async () => {
  vi.stubGlobal(
    "fetch",
    routedFetch(() => ({ ok: true, json: async () => ({ ...RESULT, rateLimit: WINDOWS(19, 183) }) })),
  );
  render(
    <I18nProvider lang="en">
      <Converter direction="tpt-to-fundsxml" />
    </I18nProvider>,
  );
  await waitFor(() =>
    expect(screen.getByTestId("rate-limit")).toHaveTextContent(
      "Limit per IP address: 20/minute, 200/hour · left: 20 this minute, 200 this hour",
    ),
  );
  fireEvent.change(screen.getByTestId("file-input"), { target: { files: [new File(["x"], "a.csv")] } });
  await waitFor(() => expect(screen.getByTestId("rate-limit")).toHaveTextContent("left: 19 this minute, 183 this hour"));
});

test("a 429 explains the limit and when the next conversion is possible", async () => {
  const fetchMock = routedFetch(() => ({
    ok: false,
    status: 429,
    statusText: "Too Many Requests",
    json: async () => ({ detail: "rate limit exceeded" }),
  }));
  fetchMock.mockImplementationOnce(() => Promise.resolve({ ok: true, json: async () => ({ convert: WINDOWS(1, 50) }) }));
  vi.stubGlobal("fetch", fetchMock);
  render(
    <I18nProvider lang="de">
      <Converter direction="tpt-to-fundsxml" />
    </I18nProvider>,
  );
  // After the 429 the limits are asked again: the minute is used up.
  fetchMock.mockImplementation((url: string) =>
    url === "/api/limits"
      ? Promise.resolve({ ok: true, json: async () => ({ convert: WINDOWS(0, 50, 42) }) })
      : url === "/api/convert"
        ? Promise.resolve({ ok: false, status: 429, statusText: "", json: async () => ({ detail: "x" }) })
        : Promise.resolve({ ok: true, json: async () => [] }),
  );
  fireEvent.change(screen.getByTestId("file-input"), { target: { files: [new File(["x"], "a.csv")] } });
  await waitFor(() =>
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Zu viele Konvertierungen: das Limit ist 20/Minute, 200/Stunde je IP-Adresse.",
    ),
  );
  expect(screen.getByText("Limit erreicht (20/Minute, 200/Stunde je IP-Adresse): nächste Konvertierung in 42 s.")).toBeInTheDocument();
});
