import { expect, test } from "@playwright/test";
import path from "node:path";

const SAMPLES = path.resolve(import.meta.dirname, "../../backend/app/samples");

test.use({ locale: "en-US" });

test("TPT sample → FundsXML download", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "TPT V8" }).click();
  await expect(page.getByText("valid against FundsXML 4.2.11 XSD")).toBeVisible();
  await expect(page.getByText("TPT V8", { exact: true }).first()).toBeVisible();
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: /Download/ }).click();
  expect((await download).suggestedFilename()).toBe("tpt_v8_sample_FundsXML.xml");
});

test("example cards: fund portfolio FundsXML → TPT, download link", async ({ page }) => {
  await page.goto("/fundsxml-to-tpt");
  await expect(page.getByTestId("samples").getByRole("listitem")).toHaveCount(6);
  const download = page.waitForEvent("download");
  await page.getByRole("link", { name: "Download fundsxml_fund_portfolio.xml" }).click();
  expect((await download).suggestedFilename()).toBe("fundsxml_fund_portfolio.xml");
  await page.getByRole("button", { name: /^Fund portfolio/ }).click();
  await expect(page.getByRole("button", { name: /Download/ })).toContainText("fundsxml_fund_portfolio_TPT_V7.xlsx");
});

test("uploaded FundsXML → TPT CSV", async ({ page }) => {
  await page.goto("/fundsxml-to-tpt");
  await page.getByText("CSV", { exact: true }).click();
  await page.getByTestId("file-input").setInputFiles(path.join(SAMPLES, "fundsxml_sample.xml"));
  await expect(page.getByRole("button", { name: /Download/ })).toContainText("fundsxml_sample_TPT_V7.csv");
  await page.getByText("V8", { exact: true }).click();
  await expect(page.getByRole("button", { name: /Download/ })).toContainText("fundsxml_sample_TPT_V8.csv");
});

test("dropping an XML on the TPT tab switches direction", async ({ page }) => {
  await page.goto("/");
  await page.getByTestId("file-input").setInputFiles(path.join(SAMPLES, "fundsxml_sample.xml"));
  await expect(page).toHaveURL(/fundsxml-to-tpt/);
  await expect(page.getByRole("button", { name: /Download/ })).toContainText(".xlsx");
});

test("openfunds sample → FundsXML, then → TPT by switching the target", async ({ page }) => {
  await page.goto("/openfunds-to-fundsxml");
  await page.getByRole("button", { name: /^Share class with holdings/ }).click();
  await expect(page.getByText("valid against FundsXML 4.2.11 XSD")).toBeVisible();
  await expect(page.getByRole("button", { name: /Download/ })).toContainText("openfunds_sample_FundsXML.xml");
  await page.getByRole("radiogroup", { name: "To" }).getByRole("radio", { name: "TPT" }).click();
  await expect(page).toHaveURL(/openfunds-to-tpt/);
  await expect(page.getByRole("button", { name: /Download/ })).toContainText("openfunds_sample_TPT_V7.xlsx");
});

test("TPT → openfunds", async ({ page }) => {
  await page.goto("/tpt-to-openfunds");
  await page.getByTestId("file-input").setInputFiles(path.join(SAMPLES, "tpt_v7_sample.xlsx"));
  await expect(page.getByRole("button", { name: /Download/ })).toContainText("tpt_v7_sample_openfunds.xlsx");
  await expect(page.getByText("openfunds 2.13.0", { exact: true })).toBeVisible();
});

test("unreadable file shows an error", async ({ page }) => {
  await page.goto("/");
  await page.getByTestId("file-input").setInputFiles({ name: "junk.csv", mimeType: "text/csv", buffer: Buffer.from("a;b\n1;2\n") });
  await expect(page.getByRole("alert")).toContainText("no TPT header row found");
});

test("mapping page lists and filters fields", async ({ page }) => {
  await page.goto("/mapping");
  await expect(page.getByText("150_LTEI_Fund_Eligibility", { exact: true })).toBeVisible();
  await page.getByRole("searchbox").fill("CouponRate");
  await expect(page.getByText("33_Coupon_rate")).toBeVisible();
  await expect(page.getByText("150_LTEI_Fund_Eligibility", { exact: true })).toHaveCount(0);
});

test("home shows the FAQ, titles follow navigation, guides render without the SPA", async ({ page }) => {
  await page.goto("/");
  await page.getByText("Is the conversion lossless?").click();
  await expect(page.getByText(/kept as custom attributes named/)).toBeVisible();
  await page.getByRole("link", { name: "Field mapping" }).click();
  await expect(page).toHaveTitle(/field mapping/);
  await page.getByRole("link", { name: "All TPT fields" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Tripartite Template (TPT) fields");
  await page.getByRole("link", { name: "CIC code of the instrument" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("TPT field 12 – CIC code of the instrument");
});
