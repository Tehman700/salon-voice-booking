import { expect, test } from "@playwright/test";

test("home page renders the product headline and statuses", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveTitle("Salon Voice");
  await expect(
    page.getByRole("heading", { level: 1, name: /receptionist, always on/i }),
  ).toBeVisible();
  await expect(page.getByLabel("Appointment statuses").getByText("Booked")).toBeVisible();
});

test("page does not scroll horizontally", async ({ page }) => {
  await page.goto("/");
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
});
