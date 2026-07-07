import { expect, test } from "@playwright/test";

test("boots and exposes deterministic playable state", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByRole("heading", { name: "ai_roguelike" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Devlog" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Docs" })).toBeVisible();
  await expect(page.locator("#game")).toBeVisible();

  const initial = await page.evaluate(() => window.__AI_ROGUELIKE_TEST__?.snapshot());
  expect(initial).toMatchObject({
    player: { hp: 10, x: 2, y: 2 },
    lastLog: "You enter the dungeon.",
    turn: 0,
  });

  const moved = await page.evaluate(() => window.__AI_ROGUELIKE_TEST__?.act({ type: "move", dx: 1, dy: 0 }));
  expect(moved).toMatchObject({
    player: { hp: 10, x: 3, y: 2 },
    lastLog: "You move.",
    turn: 1,
  });
});
