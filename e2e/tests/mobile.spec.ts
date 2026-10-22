import { expect, test } from "@playwright/test";

test.use({ locale: "de-DE" });

test("result fits the viewport and download stays reachable", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: /^Gemischtes Portfolio/ }).click();
  const download = page.getByRole("button", { name: /Herunterladen/ });
  await expect(download).toBeInViewport();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(1);
});
