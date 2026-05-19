import { expect, test } from "@playwright/test";

test("home page renders heading", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toContainText(
    "ノートブック",
  );
});

test("create notebook flow", async ({ page }) => {
  await page.goto("/");
  // wait for JS to hydrate (networkidle ensures Svelte 5 event delegation is active)
  await page.waitForLoadState("networkidle");
  await page.getByRole("button", { name: /新規ノートブック/ }).click();
  // wait for modal to appear
  await expect(page.getByRole("dialog")).toBeVisible({ timeout: 10_000 });
  await page.getByRole("textbox", { name: /名前/ }).fill("E2E Test Notebook");
  await page.getByRole("button", { name: "作成" }).click();
  // we land on the detail page
  await expect(page).toHaveURL(/\/notebooks\//, { timeout: 15_000 });
  await expect(page.getByRole("heading", { level: 2 })).toContainText(
    "E2E Test Notebook",
  );
});
