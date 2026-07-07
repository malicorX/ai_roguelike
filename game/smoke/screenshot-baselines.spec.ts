import { expect, test } from "@playwright/test";

test.skip(process.platform !== "linux", "Screenshot baselines are generated and verified on Linux to avoid platform rendering drift.");

test("keeps deterministic canvas screenshot baselines", async ({ page }) => {
  await page.goto("/");

  const canvas = page.locator("#game");
  await expect(canvas).toHaveScreenshot("start-room.png", {
    maxDiffPixelRatio: 0.01,
  });

  await page.evaluate(() => window.__AI_ROGUELIKE_TEST__?.act({ type: "move", dx: 1, dy: 0 }));
  await expect(canvas).toHaveScreenshot("after-first-move.png", {
    maxDiffPixelRatio: 0.01,
  });
});
