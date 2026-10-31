import type { Page } from "@playwright/test";

// Demo-mode sample accounts (NEXT_PUBLIC_API_MOCKS=true), see src/mocks/seed.ts.
export const DEMO_PASSWORD = "demo-password";

export async function signIn(page: Page, email = "owner@lumiere.pk") {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(DEMO_PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  // Wait until sign-in has finished, or a following navigation would cancel it.
  await page.waitForURL((url) => !url.pathname.endsWith("/login"));
}
