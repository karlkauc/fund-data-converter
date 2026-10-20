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

test("unreadable file shows an error", async ({ page }) => {
  await page.goto("/");
  await page.getByTestId("file-input").setInputFiles({ name: "junk.csv", mimeType: "text/csv", buffer: Buffer.from("a;b\n1;2\n") });
  await expect(page.getByRole("alert")).toContainText("no TPT header row found");
});

test("mapping page lists and filters fields", async ({ page }) => {
  await page.goto("/mapping");
  await expect(page.getByText("150_LTEI_Fund_Elligibility", { exact: true })).toBeVisible();
  await page.getByRole("searchbox").fill("CouponRate");
  await expect(page.getByText("33_Coupon_rate")).toBeVisible();
  await expect(page.getByText("150_LTEI_Fund_Elligibility", { exact: true })).toHaveCount(0);
});
