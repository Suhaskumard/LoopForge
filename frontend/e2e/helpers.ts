import AxeBuilder from "@axe-core/playwright";
import { expect, type APIRequestContext, type Page } from "@playwright/test";

export const PASSWORD = "e2e-pass-123";
const API = "http://127.0.0.1:8000";

let counter = 0;
/** A fresh address per call, so specs never depend on each other or on run order. */
export const uniqueEmail = (tag: string) => `${tag}-${Date.now()}-${++counter}@example.com`;

export async function register(page: Page, email: string): Promise<void> {
  await page.goto("/login");
  await page.getByRole("button", { name: /Need an account/ }).click();
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("heading", { name: "Command Center" })).toBeVisible();
}

export async function signIn(page: Page, email: string, password = PASSWORD): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Command Center" })).toBeVisible();
}

/** The newest mail to `to` from the demo server's test outbox; waits for it to arrive. */
export async function latestMail(request: APIRequestContext, to: string, subject: RegExp) {
  let found: { to: string; subject: string; body: string } | undefined;
  await expect
    .poll(
      async () => {
        const rows = (await (await request.get(`${API}/__test__/outbox`, { params: { to } })).json()) as {
          to: string;
          subject: string;
          body: string;
        }[];
        found = rows.filter((m) => subject.test(m.subject)).at(-1);
        return found !== undefined;
      },
      { timeout: 15_000 },
    )
    .toBe(true);
  return found!;
}

/** The path+query of the first link in a mail body, so the test follows it on the dev server. */
export function linkPath(body: string): string {
  const m = /https?:\/\/[^\s/]+(\/[^\s]+)/.exec(body);
  if (!m) throw new Error(`no link in mail:\n${body}`);
  return m[1];
}

/** Fails on serious or critical accessibility violations (the Phase 15 gate). */
export async function expectNoSeriousA11yViolations(page: Page, label: string): Promise<void> {
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
  const bad = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  expect(
    bad.map((v) => `${v.id} (${v.impact}): ${v.nodes.map((n) => n.target.join(" ")).slice(0, 3).join(" | ")}`),
    `axe violations on ${label}`,
  ).toEqual([]);
}
