import { fireEvent, render, screen } from "@testing-library/react";
import { ApiDocsPage } from "../src/components/ApiDocsPage";
import { I18nProvider } from "../src/lib/i18n";

test("the API page documents options, examples and issue codes", () => {
  render(
    <I18nProvider lang="de">
      <ApiDocsPage />
    </I18nProvider>,
  );
  expect(screen.getByRole("heading", { name: "Parameter" })).toBeInTheDocument();
  expect(screen.getAllByText("response").length).toBeGreaterThan(0);
  expect(screen.getByText("block_value_rejected")).toBeInTheDocument();
  expect(screen.getByText("Vom TPT-Block nicht übernommen – als CustomAttribute erhalten")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Python" }));
  expect(screen.getByText(/import requests/)).toBeInTheDocument();
});
