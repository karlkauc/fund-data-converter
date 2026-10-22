import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";
import { Converter } from "../src/components/Converter";
import { directionOf, guessSource, makeDirection, routeOf } from "../src/lib/directions";
import { I18nProvider, ISSUE_CODES, issueText } from "../src/lib/i18n";
import { ROUTES, TITLES } from "../src/lib/router";

test("directions and routes", () => {
  expect(makeDirection("tpt", "openfunds")).toBe("tpt-to-openfunds");
  expect(makeDirection("openfunds", "openfunds")).toBe("openfunds-to-fundsxml");
  expect(routeOf("tpt-to-fundsxml")).toBe("");
  expect(directionOf("")).toBe("tpt-to-fundsxml");
  expect(directionOf("openfunds-to-tpt")).toBe("openfunds-to-tpt");
  expect(directionOf("mapping")).toBeNull();
  for (const r of ROUTES) expect(TITLES[r]).toBeTruthy();
  expect(guessSource(new File([""], "a.xml"), "tpt")).toBe("fundsxml");
  expect(guessSource(new File([""], "a.zip"), "tpt")).toBe("openfunds");
  expect(guessSource(new File([""], "a.xlsx"), "openfunds")).toBe("openfunds");
  expect(guessSource(new File([""], "a.xlsx"), "fundsxml")).toBe("tpt");
});

test("every issue code has a German text", () => {
  for (const code of ISSUE_CODES) expect(issueText("de", code, "")).not.toBe("");
});

test("the target of the page is sent with the file", async () => {
  const fetchMock = vi.fn().mockResolvedValue({ ok: false, status: 422, statusText: "x", json: async () => ({ detail: "nope" }) });
  vi.stubGlobal("fetch", fetchMock);
  render(
    <I18nProvider lang="en">
      <Converter direction="tpt-to-openfunds" />
    </I18nProvider>,
  );
  expect(screen.getByRole("radio", { name: "openfunds", checked: true })).toBeInTheDocument();
  fireEvent.change(screen.getByTestId("file-input"), { target: { files: [new File(["x"], "a.xlsx")] } });
  await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
  const [, init] = fetchMock.mock.calls.find(([u]) => u === "/api/convert")!;
  const form = init.body as FormData;
  expect(form.get("target")).toBe("openfunds");
  expect(form.get("non_openfunds_columns")).toBe("true");
});
