import { expect, test } from "@playwright/test";
import {
  PASSWORD,
  expectNoSeriousA11yViolations,
  latestMail,
  linkPath,
  register,
  signIn,
  uniqueEmail,
} from "./helpers";

test.describe("a new user's first session", () => {
  test("signs up, verifies the email, creates a task from a template, watches it finish, reads the report and downloads the zip", async ({
    page,
    request,
  }) => {
    const email = uniqueEmail("first");
    await register(page, email);

    // email verification
    await expect(page.getByTestId("verify-banner")).toContainText(email);
    const mail = await latestMail(request, email, /Verify your LoopForge email/);
    await page.goto(linkPath(mail.body));
    await expect(page.getByText("Your email address is verified")).toBeVisible();
    await page.goto("/");
    await expect(page.getByTestId("verify-banner")).toHaveCount(0);

    // a template pre-fills the form
    await page.getByRole("link", { name: "New task" }).first().click();
    await page.getByLabel("Template").selectOption("crud-api");
    await expect(page.getByLabel("Natural-language requirement")).toHaveValue(/FastAPI service/);
    await expect(page.getByLabel(/Acceptance criteria/)).toHaveValue(/All five endpoints/);
    // The scripted demo LLM tells one fixed story that has no criteria to check, so clear them here.
    await page.getByLabel(/Acceptance criteria/).fill("");
    await page.getByRole("button", { name: /Create|Start/ }).first().click();

    // the loop runs (scripted: defect, failing tests, repair, pass) and the task completes
    await expect(page.getByRole("heading", { name: "Live Workflow" })).toBeVisible();
    await expect(page.locator(".badge", { hasText: /^COMPLETED$/ })).toBeVisible({ timeout: 45_000 });

    // report and zip download
    await page.getByRole("link", { name: "Final Report" }).click();
    await expect(page.getByTestId("outcome")).toContainText("Accepted");
    await expect(page.getByTestId("failure-explanation")).toHaveCount(0); // accepted tasks have none
    const [download] = await Promise.all([
      page.waitForEvent("download"),
      page.getByRole("button", { name: "Code (.zip)" }).click(),
    ]);
    expect(download.suggestedFilename()).toMatch(/^task-.*\.zip$/);

    // a finished task notifies its owner
    await page.goto("/");
    await page.getByRole("button", { name: /Notifications/ }).click();
    await expect(page.getByRole("region", { name: "Notification list" })).toContainText("Task finished");
  });

  test("an approval gate pauses the run, takes a review comment and resumes on approval", async ({ page }) => {
    await register(page, uniqueEmail("gate"));
    await page.goto("/tasks/new");
    await page.getByLabel(/Pause for my approval/).check();
    await page.getByRole("button", { name: /Create|Start/ }).first().click();

    await expect(page.getByTestId("approvals")).toBeVisible({ timeout: 30_000 });
    await page.getByLabel("Comment").fill("Please keep the routes small");
    await page.getByRole("button", { name: "Add comment" }).click();
    await expect(page.getByTestId("review-comments")).toContainText("Please keep the routes small");

    await page.getByRole("button", { name: "Approve and continue" }).click();
    await expect(page.locator(".badge", { hasText: /^COMPLETED$/ })).toBeVisible({ timeout: 45_000 });
  });
});

test.describe("account recovery and sessions", () => {
  test("a forgotten password is reset by email, ends other sessions and the old password stops working", async ({
    browser,
    page,
    request,
  }) => {
    const email = uniqueEmail("reset");
    await register(page, email);

    // a second browser is signed in too
    const other = await browser.newPage();
    await signIn(other, email);

    const fresh = await browser.newPage();
    await fresh.goto("/forgot-password");
    await fresh.getByLabel("Email").fill(email);
    await fresh.getByRole("button", { name: "Send reset link" }).click();
    await expect(fresh.getByText(/If that address is registered/)).toBeVisible();

    const mail = await latestMail(request, email, /Reset your LoopForge password/);
    await fresh.goto(linkPath(mail.body));
    await fresh.getByLabel("New password").fill("brand-new-pass-9");
    await fresh.getByRole("button", { name: "Change password" }).click();
    await expect(fresh.getByText(/Password changed/)).toBeVisible();

    // the old session can no longer use the API
    await other.reload();
    await expect(other.getByRole("button", { name: "Sign in" })).toBeVisible();

    await signIn(fresh, email, "brand-new-pass-9");
    await fresh.context().clearCookies();
    const stale = await browser.newPage();
    await stale.goto("/login");
    await stale.getByLabel("Email").fill(email);
    await stale.getByLabel("Password").fill(PASSWORD);
    await stale.getByRole("button", { name: "Sign in" }).click();
    await expect(stale.getByRole("alert")).toContainText("Incorrect email or password");
  });

  test("the unknown-address reset page gives exactly the same answer", async ({ page }) => {
    await page.goto("/forgot-password");
    await page.getByLabel("Email").fill(uniqueEmail("ghost"));
    await page.getByRole("button", { name: "Send reset link" }).click();
    await expect(page.getByText(/If that address is registered/)).toBeVisible();
  });

  test("the sessions page lists devices and revokes another one", async ({ browser, page }) => {
    const email = uniqueEmail("sess");
    await register(page, email);
    const other = await browser.newPage();
    await signIn(other, email);

    await page.goto("/settings");
    await expect(page.getByText("this session")).toBeVisible();
    const signOut = page.getByRole("button", { name: "Sign out" }).last();
    await expect(signOut).toBeVisible();
    await signOut.click();
    await expect(page.getByRole("button", { name: "Sign out" })).toHaveCount(1); // only the nav link remains

    await other.reload();
    await other.goto("/");
    await expect(other.getByRole("button", { name: "Sign in" })).toBeVisible({ timeout: 20_000 });
  });
});

test.describe("organizations", () => {
  test("an admin invites by email, the invitee joins, switches organization and the admin page is role-gated", async ({
    browser,
    page,
    request,
  }) => {
    const admin = uniqueEmail("boss");
    await register(page, admin);

    await page.goto("/admin");
    await page.getByRole("tab", { name: "Members" }).click();
    const invitee = uniqueEmail("newbie");
    await page.getByLabel("Email to invite").fill(invitee);
    await page.getByRole("button", { name: "Send invitation" }).click();
    await expect(page.getByText(/If the address can receive an invitation/)).toBeVisible();
    await expect(page.getByRole("cell", { name: invitee })).toBeVisible();

    // the invitee signs up, verifies and accepts
    const guest = await browser.newPage();
    await register(guest, invitee);
    const verify = await latestMail(request, invitee, /Verify your LoopForge email/);
    await guest.goto(linkPath(verify.body));
    await expect(guest.getByText("Your email address is verified")).toBeVisible();
    const invite = await latestMail(request, invitee, /invited to/);
    await guest.goto(linkPath(invite.body));
    await guest.getByRole("button", { name: "Accept invitation" }).click();
    await expect(guest.getByText("You joined the organization")).toBeVisible();

    // two organizations now: the switcher appears, and the role there is "developer"
    await guest.goto("/");
    const switcher = guest.getByLabel("Organization");
    await expect(switcher).toBeVisible();
    await expect(guest.getByTestId("role")).toHaveText("developer");
    await guest.goto("/admin");
    await expect(guest.getByText("Organization settings are for admins")).toBeVisible();

    // switch back to the personal organization, where this user is an admin
    await switcher.selectOption({ index: 0 });
    await expect(guest.getByTestId("role")).toBeVisible();
  });

  test("per-member limits can be saved on the Usage & limits tab", async ({ page }) => {
    await register(page, uniqueEmail("limits"));
    await page.goto("/admin");
    await page.getByRole("tab", { name: "Usage & limits" }).click();
    await expect(page.getByRole("heading", { name: "Per-member limits" })).toBeVisible();
    const row = page.getByRole("row").filter({ hasText: "@example.com" }).first();
    await row.getByRole("textbox").nth(1).fill("50");
    await row.getByRole("button", { name: /Save limits/ }).click();
    await expect(page.getByText(/Saved limits for/)).toBeVisible();
    await page.goto("/settings");
    await expect(page.getByText("0 / 50")).toBeVisible();
  });
});

test.describe("accessibility (axe: no serious or critical violations)", () => {
  test("public pages", async ({ page }) => {
    for (const path of ["/login", "/forgot-password", "/reset-password?token=x", "/verify-email?token=x"]) {
      await page.goto(path);
      await page.waitForLoadState("networkidle");
      await expectNoSeriousA11yViolations(page, path);
    }
  });

  test("signed-in screens", async ({ page }) => {
    await register(page, uniqueEmail("a11y"));
    for (const path of ["/", "/tasks/new", "/analytics", "/admin", "/settings"]) {
      await page.goto(path);
      await page.waitForLoadState("networkidle");
      await expectNoSeriousA11yViolations(page, path);
    }
  });
});
