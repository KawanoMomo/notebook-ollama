import { expect, test } from "@playwright/test";

test("home page renders heading", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toContainText(
    "ノートブック",
  );
});

test("create notebook flow", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: /新規ノートブック/ }).click();
  await page.getByLabel(/名前/).fill("E2E Test Notebook");
  await page.getByRole("button", { name: "作成" }).click();
  // we land on the detail page
  await expect(page).toHaveURL(/\/notebooks\//);
  await expect(page.getByRole("heading", { level: 2 })).toContainText(
    "E2E Test Notebook",
  );
});
