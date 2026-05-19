import { expect, test } from "@playwright/test";

test.describe("notebook detail", () => {
  let notebookId: string;

  test.beforeEach(async ({ page, request }) => {
    // Create a notebook via API
    const r = await request.post("http://localhost:8765/api/notebooks", {
      data: { name: "E2E Detail Test" },
    });
    const body = await r.json();
    notebookId = body.id;
    await page.goto(`/notebooks/${notebookId}`);
  });

  test.afterEach(async ({ request }) => {
    if (notebookId) {
      await request.delete(`http://localhost:8765/api/notebooks/${notebookId}`);
    }
  });

  test("renders 3-column layout", async ({ page }) => {
    await expect(page.getByRole("heading", { level: 2 })).toContainText(
      "E2E Detail Test",
    );
    await expect(page.getByPlaceholder("ソースを検索")).toBeVisible();
    await expect(page.getByPlaceholder(/質問を入力/)).toBeVisible();
  });

  test("upload markdown shows in sources panel", async ({ page }) => {
    await page.getByRole("button", { name: /追加/ }).first().click();
    await page.setInputFiles('input[type="file"]', {
      name: "hello.md",
      mimeType: "text/markdown",
      buffer: Buffer.from("# Hello\n\nE2E body."),
    });
    await page.getByLabel("ソース追加").getByRole("button", { name: "追加" }).click();
    await expect(page.getByText("hello.md")).toBeVisible({ timeout: 10_000 });
  });
});
