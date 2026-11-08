import { expect, test, type Page } from "@playwright/test";
import { expectNoSeriousA11yViolations, register, uniqueEmail } from "./helpers";

/** No horizontal page scroll at phone width: the document is never wider than the viewport. */
async function expectNoHorizontalScroll(page: Page, label: string) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow, `${label} scrolls sideways by ${overflow}px`).toBeLessThanOrEqual(1);
}

test("the main screens fit a phone and stay accessible", async ({ page }) => {
  await page.goto("/login");
  await expectNoHorizontalScroll(page, "/login");
  await expectNoSeriousA11yViolations(page, "/login (mobile)");

  await register(page, uniqueEmail("phone"));
  for (const path of ["/", "/tasks/new", "/settings", "/admin"]) {
    await page.goto(path);
    await page.waitForLoadState("networkidle");
    await expectNoHorizontalScroll(page, path);
    await expectNoSeriousA11yViolations(page, `${path} (mobile)`);
  }
});
