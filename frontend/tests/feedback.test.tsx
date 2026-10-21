import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";
import { Converter } from "../src/components/Converter";
import { FeedbackDialog } from "../src/components/FeedbackDialog";
import { openFeedback } from "../src/lib/feedback";
import { I18nProvider } from "../src/lib/i18n";

test("feedback is sent with the context, never the file", async () => {
  const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 204 });
  vi.stubGlobal("fetch", fetchMock);
  render(
    <I18nProvider lang="en">
      <FeedbackDialog />
    </I18nProvider>,
  );
  act(() => openFeedback({ direction: "fundsxml-to-tpt", tptVersion: "V8", errorDetail: "no positions found" }));
  expect(screen.getByRole("dialog")).toHaveTextContent("Error attached: no positions found");
  fireEvent.change(screen.getByPlaceholderText(/What happened/), { target: { value: " Field 12 is wrong " } });
  fireEvent.click(screen.getByRole("button", { name: "Send" }));
  await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Thanks"));
  const [url, init] = fetchMock.mock.calls[0];
  expect(url).toBe("/api/feedback");
  expect(JSON.parse(init.body)).toEqual({
    message: "Field 12 is wrong",
    page: "/",
    direction: "fundsxml-to-tpt",
    tpt_version: "V8",
    error_detail: "no positions found",
    website: "",
  });
});

test("a failed send is reported", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({ ok: false, status: 503, statusText: "x", json: async () => ({ detail: "db down" }) }),
  );
  render(
    <I18nProvider lang="de">
      <FeedbackDialog />
    </I18nProvider>,
  );
  act(() => openFeedback());
  fireEvent.change(screen.getByRole("textbox", { name: "Deine Nachricht" }), { target: { value: "hallo" } });
  fireEvent.click(screen.getByRole("button", { name: "Senden" }));
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Senden fehlgeschlagen: db down"));
});

test("a conversion error can be reported from the error panel", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({ ok: false, status: 422, statusText: "x", json: async () => ({ detail: "no TPT header row found" }) }),
  );
  render(
    <I18nProvider lang="en">
      <Converter direction="tpt-to-fundsxml" />
      <FeedbackDialog />
    </I18nProvider>,
  );
  fireEvent.change(screen.getByTestId("file-input"), { target: { files: [new File(["x"], "a.csv")] } });
  fireEvent.click(await screen.findByRole("button", { name: "Report a problem" }));
  expect(screen.getByRole("dialog")).toHaveTextContent("Error attached: no TPT header row found");
});
