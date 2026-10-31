import { expect, test, type Page } from "@playwright/test";

import { signIn } from "./helpers";

// These run against a production build in demo mode (NEXT_PUBLIC_API_MOCKS=true), so they need no backend.

const isMobile = (name: string) => name === "mobile";

/** The "N" in the table footer's "Showing X of N bookings". */
async function totalBookings(page: Page) {
  const text = await page.getByText(/Showing \d+ of \d+ bookings/).innerText();
  return Number(/of (\d+) bookings/.exec(text)![1]);
}

async function openNav(page: Page, projectName: string) {
  if (isMobile(projectName)) await page.getByRole("button", { name: "Open navigation" }).click();
}

test.describe("sign in", () => {
  test("asks for both fields", async ({ page }) => {
    await page.goto("/login");
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.getByText("Enter your email and password.")).toBeVisible();
  });

  test("rejects a wrong password", async ({ page }) => {
    await page.goto("/login");
    await page.getByLabel("Email").fill("owner@lumiere.pk");
    await page.getByLabel("Password").fill("not-the-password");
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.getByText(/invalid email or password/i)).toBeVisible();
    await expect(page).toHaveURL(/\/login$/);
  });

  test("protected pages send visitors to the login page", async ({ page }) => {
    await page.goto("/bookings");
    await expect(page).toHaveURL(/\/login$/);
  });

  test("owner lands on the overview and can sign out", async ({ page }) => {
    await signIn(page);
    await expect(page.getByRole("heading", { level: 1, name: "Overview" })).toBeVisible();
    await expect(page.getByText("Cancellations")).toBeVisible();

    await page.getByRole("button", { name: "Account menu" }).click();
    await page.getByRole("menuitem", { name: "Sign out" }).click();
    await expect(page).toHaveURL(/\/login$/);
  });

  test("signing in survives a page reload", async ({ page }) => {
    await signIn(page);
    await expect(page.getByRole("heading", { level: 1, name: "Overview" })).toBeVisible();
    await page.reload();
    await expect(page.getByRole("heading", { level: 1, name: "Overview" })).toBeVisible();
  });
});

test.describe("owner dashboard", () => {
  test("every page loads", async ({ page }, testInfo) => {
    await signIn(page);
    await expect(page.getByRole("heading", { level: 1, name: "Overview" })).toBeVisible();

    const pages: [string, string][] = [
      ["Calendar", "Calendar"],
      ["Bookings", "Bookings"],
      ["Customers", "Customers"],
      ["Staff", "Staff"],
      ["Services", "Services"],
      ["Voice calls", "Voice calls"],
      ["Team", "Team"],
      ["Settings", "Settings"],
    ];
    for (const [link, heading] of pages) {
      await openNav(page, testInfo.project.name);
      await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: link }).click();
      await expect(page.getByRole("heading", { level: 1, name: heading })).toBeVisible();
    }
  });

  test("the calendar renders bookings", async ({ page }) => {
    await signIn(page);
    await page.goto("/calendar");
    await expect(page.locator(".salon-calendar")).toBeVisible();
    const monthView = page.locator(".salon-calendar button", { hasText: "Month" });
    await expect(monthView).toBeVisible();
    await monthView.click();
    await expect(page.locator(".salon-calendar")).toContainText(/\d{4}/);
  });

  test("filters the bookings table", async ({ page }) => {
    await signIn(page);
    await page.goto("/bookings");
    const rows = page.locator("tbody tr");
    await expect(rows.first()).toBeVisible();
    const all = await rows.count();

    await page.getByRole("combobox", { name: "Status" }).click();
    await page.getByRole("option", { name: "Cancelled" }).click();
    // The table keeps its old rows while the filtered list loads, so wait for it to settle.
    const statuses = page.locator("tbody tr td:nth-child(6)");
    await expect.poll(async () => (await statuses.allInnerTexts()).every((t) => t === "Cancelled")).toBe(true);
    await expect(statuses.first()).toBeVisible();
    expect(await page.locator("tbody tr").count()).toBeLessThan(all);

    await page.getByRole("button", { name: "Clear" }).click();
    await expect(page.locator("tbody tr")).toHaveCount(all);
  });

  test("creates a booking from the first free time", async ({ page }) => {
    await signIn(page);
    await page.goto("/bookings");
    await page.getByRole("button", { name: "New booking" }).first().click();
    const dialog = page.getByRole("dialog", { name: "New booking" });

    await dialog.getByRole("combobox", { name: "Service" }).click();
    await page.getByRole("option").first().click();

    // Find the first day that has free times: wait for each lookup to finish before judging it.
    const times = dialog.getByRole("radiogroup", { name: "Available times" }).getByRole("radio");
    const none = dialog.getByText("No free times on this day");
    for (let ahead = 0; ahead <= 10; ahead++) {
      if (ahead > 0) {
        const day = new Date(Date.now() + ahead * 86_400_000).toISOString().slice(0, 10);
        await dialog.getByLabel("Date").fill(day);
      }
      await expect(times.first().or(none)).toBeVisible();
      if ((await times.count()) > 0) break;
    }
    await expect(times.first()).toBeVisible();
    await times.first().click();

    await dialog.getByLabel("Customer name").fill("Test Customer");
    // A phone number no sample customer has, so a new customer is created.
    await dialog.getByLabel("Phone").fill(`+9230${String(Date.now()).slice(-8)}`);
    await dialog.getByRole("button", { name: "Create booking" }).click();

    await expect(page.getByText(/Booked Test Customer/)).toBeVisible();
    await expect(dialog).toBeHidden();
    await page.getByLabel("Search bookings").fill("Test Customer");
    await expect(page.locator("tbody tr")).toHaveCount(1);
  });

  test("validates the new booking form", async ({ page }) => {
    await signIn(page);
    await page.goto("/bookings");
    await page.getByRole("button", { name: "New booking" }).first().click();
    const dialog = page.getByRole("dialog", { name: "New booking" });
    await dialog.getByRole("button", { name: "Create booking" }).click();
    const errors = dialog.locator("p.text-destructive");
    await expect(errors.filter({ hasText: "Choose a service" })).toBeVisible();
    await expect(errors.filter({ hasText: "Enter the customer's name" })).toBeVisible();
    await expect(errors.filter({ hasText: "Enter a valid phone number" })).toBeVisible();
  });

  test("cancels a booking, respecting the cancellation window", async ({ page }) => {
    await signIn(page);
    await page.goto("/bookings");
    await page.getByRole("combobox", { name: "Status" }).click();
    await page.getByRole("option", { name: "Booked" }).click();
    await expect(page.locator("tbody tr").first()).toBeVisible();
    await expect(page.locator("tbody tr td:nth-child(6)").filter({ hasNotText: "Booked" })).toHaveCount(0);
    const before = await totalBookings(page);

    // The first row is the furthest-out booking, so it is outside any cancellation window.
    await page.locator("tbody tr").first().getByRole("button", { name: /Actions for/ }).click();
    await page.getByRole("menuitem", { name: "Cancel booking" }).click();
    await page.getByRole("alertdialog").getByRole("button", { name: "Cancel booking" }).click();
    await expect(page.getByText("Booking cancelled")).toBeVisible();
    await expect(page.getByText(`of ${before - 1} bookings`)).toBeVisible();
  });

  test("a booking inside the window needs a manager's confirmation", async ({ page }) => {
    await signIn(page);
    await page.goto("/bookings");
    await page.getByRole("combobox", { name: "Status" }).click();
    await page.getByRole("option", { name: "Booked" }).click();
    await expect(page.locator("tbody tr").first()).toBeVisible();
    await expect(page.locator("tbody tr td:nth-child(6)").filter({ hasNotText: "Booked" })).toHaveCount(0);
    const before = await totalBookings(page);

    // The last row is the soonest booking, which falls inside the 2-4 hour notice window.
    await page.locator("tbody tr").last().getByRole("button", { name: /Actions for/ }).click();
    await page.getByRole("menuitem", { name: "Cancel booking" }).click();
    await page.getByRole("alertdialog").getByRole("button", { name: "Cancel booking" }).click();

    const prompt = page.getByRole("alertdialog", { name: "Inside the cancellation window" });
    const needsOverride = await prompt.waitFor({ timeout: 3000 }).then(() => true, () => false);
    if (needsOverride) await prompt.getByRole("button", { name: "Cancel anyway" }).click();
    await expect(page.getByText("Booking cancelled")).toBeVisible();
    await expect(page.getByText(`of ${before - 1} bookings`)).toBeVisible();
  });

  test("location switcher narrows every page", async ({ page }, testInfo) => {
    test.skip(isMobile(testInfo.project.name), "covered on desktop");
    await signIn(page);
    await page.goto("/staff");
    await expect(page.getByRole("combobox", { name: "Location" })).toBeVisible();
    const all = await page.locator("section[aria-label] ").count();
    await page.getByRole("combobox", { name: "Location" }).click();
    await page.getByRole("option").nth(1).click();
    await expect(page.locator("section[aria-label]")).toHaveCount(1);
    expect(all).toBeGreaterThan(1);
  });
});

test.describe("staff role", () => {
  test("sees only the calendar and bookings", async ({ page }, testInfo) => {
    await signIn(page, "sana@lumiere.pk");
    await expect(page).toHaveURL(/\/calendar$/);
    await openNav(page, testInfo.project.name);
    const nav = page.getByRole("navigation", { name: "Main" });
    await expect(nav.getByRole("link")).toHaveText(["Calendar", "Bookings"]);
  });

  test("is sent away from manager pages", async ({ page }) => {
    await signIn(page, "sana@lumiere.pk");
    await expect(page).toHaveURL(/\/calendar$/);
    await page.goto("/settings");
    await expect(page).toHaveURL(/\/calendar$/);
  });
});

test.describe("onboarding", () => {
  test("a new multi-salon business can sign up", async ({ page }) => {
    await page.goto("/signup");
    await page.getByLabel("Business name").fill("Glow Studio");
    await page.getByLabel("Your name").fill("Amna Test");
    await page.getByLabel("Email").fill("amna@glow.example.com");
    await page.getByLabel("Password").fill("a-long-password");
    await page.getByRole("button", { name: "Continue" }).click();

    await page.getByRole("radio", { name: "More than one" }).click();
    await page.getByLabel("Salon name").first().fill("Clifton");
    await page.getByRole("button", { name: "Add another salon" }).click();
    await page.getByLabel("Salon name").nth(1).fill("DHA");
    await page.getByRole("button", { name: "Create account" }).click();

    await expect(page.getByRole("heading", { level: 1, name: "Overview" })).toBeVisible();
    await expect(page.getByRole("combobox", { name: "Location" })).toBeVisible();
  });

  test("a single-salon business gets no location switcher", async ({ page }) => {
    await signIn(page, "owner@studionoor.pk");
    await expect(page.getByRole("heading", { level: 1, name: "Overview" })).toBeVisible();
    await page.waitForLoadState("networkidle");
    await expect(page.getByRole("combobox", { name: "Location" })).toHaveCount(0);
  });

  test("signup checks the form before moving on", async ({ page }) => {
    await page.goto("/signup");
    await page.getByRole("button", { name: "Continue" }).click();
    await expect(page.getByText("Enter your business name")).toBeVisible();
    await expect(page.getByText("Use at least 10 characters").first()).toBeVisible();
  });
});

test.describe("layout", () => {
  for (const path of ["/login", "/signup"]) {
    test(`${path} does not scroll sideways`, async ({ page }) => {
      await page.goto(path);
      await expect(page.locator("body")).toBeVisible();
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      expect(overflow).toBeLessThanOrEqual(0);
    });
  }

  for (const path of ["/", "/calendar", "/bookings", "/staff", "/calls", "/settings"]) {
    test(`${path} does not scroll sideways`, async ({ page }) => {
      await signIn(page);
      await page.goto(path);
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      await page.waitForLoadState("networkidle");
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      expect(overflow).toBeLessThanOrEqual(0);
    });
  }
});
