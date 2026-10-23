import { afterEach, expect, test, vi } from "vitest";
import { fileType, reportUsage } from "../src/lib/usage";

afterEach(() => vi.restoreAllMocks());

test("a usage event carries fixed values only and survives the page", () => {
  const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(null, { status: 204 }));
  reportUsage({ type: "download", target: "xlsx", direction: "fundsxml-to-tpt" });
  const [url, init] = fetchMock.mock.calls[0];
  expect(url).toBe("/api/usage/event");
  expect(init?.keepalive).toBe(true);
  expect((init?.headers as Record<string, string>)["X-Client"]).toBe("web");
  expect(JSON.parse(String(init?.body))).toEqual({ type: "download", target: "xlsx", direction: "fundsxml-to-tpt" });
});

test("a failing statistics call is ignored", () => {
  vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("offline"));
  expect(() => reportUsage({ type: "handoff", target: "validator", outcome: "timeout" })).not.toThrow();
});

test("the download type follows the file name", () => {
  expect(fileType("a_FundsXML.xml")).toBe("xml");
  expect(fileType("a_TPT_V7.CSV")).toBe("csv");
  expect(fileType("a_FundsXML.xml.zip")).toBe("zip");
  expect(fileType("a_openfunds.xlsx")).toBe("xlsx");
});
