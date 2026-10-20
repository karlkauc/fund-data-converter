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
  const [url, init] = fetchMock.mock.calls[0];
  expect(url).toBe("/api/convert");
  expect((init.body as FormData).get("include_core")).toBe("true");
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
