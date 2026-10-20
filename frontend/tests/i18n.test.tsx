import { render, screen } from "@testing-library/react";
import { I18nProvider, issueText, useI18n } from "../src/lib/i18n";

function Probe() {
  const { t } = useI18n();
  return <p>{t("xsdInvalid", { n: 3 })}</p>;
}

test("translations interpolate variables", () => {
  render(
    <I18nProvider lang="de">
      <Probe />
    </I18nProvider>,
  );
  expect(screen.getByText("3 XSD-Validierungsfehler")).toBeInTheDocument();
});

test("issue texts fall back to the backend message", () => {
  expect(issueText("en", "mandatory_missing", "x", { name: "5_NAV", n: 2 })).toBe(
    "Mandatory field 5_NAV is empty in 2 row(s).",
  );
  expect(issueText("de", "unknown_code", "backend text")).toBe("backend text");
});
