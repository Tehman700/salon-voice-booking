import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

import { signIn } from "./helpers";

// Scanning a full page with axe can take a while on busy pages.
test.setTimeout(90_000);

const PAGES = ["/login", "/signup"];
const APP_PAGES = ["/", "/bookings", "/customers", "/services", "/staff", "/calls", "/team", "/settings"];

async function violations(page: import("@playwright/test").Page) {
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
  return results.violations
    .filter((v) => v.impact === "serious" || v.impact === "critical")
    .map((v) => `${v.id}: ${v.help} (${v.nodes.length} elements, e.g. ${v.nodes[0]?.target.join(" ")})`);
}

for (const path of PAGES) {
  test(`${path} has no serious accessibility violations`, async ({ page }) => {
    await page.goto(path);
    await expect(page.locator("form")).toBeVisible();
    expect(await violations(page)).toEqual([]);
  });
}

for (const path of APP_PAGES) {
  test(`${path} has no serious accessibility violations (signed in)`, async ({ page }) => {
    await signIn(page);
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await page.waitForLoadState("networkidle");
    // Tables render after their data arrives; check the settled page, not the loading state.
    await page.locator("tbody tr").first().waitFor({ timeout: 3000 }).catch(() => undefined);
    expect(await violations(page)).toEqual([]);
  });
}
