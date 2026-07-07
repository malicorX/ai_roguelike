import { expect, test } from "@playwright/test";

const TILE_SIZE = 48;
const PLAYER_COLOR = { r: 248, g: 225, b: 108 };
const ENEMY_COLOR = { r: 255, g: 107, b: 107 };

test("renders player and enemy with readable distinct colors", async ({ page }) => {
  await page.goto("/");

  const visual = await page.evaluate(
    ({ enemyColor, playerColor, tileSize }) => {
      const canvas = document.querySelector<HTMLCanvasElement>("#game");
      if (!canvas) {
        throw new Error("Missing game canvas.");
      }

      const context = canvas.getContext("2d");
      if (!context) {
        throw new Error("Missing canvas context.");
      }

      function countColorNearTile(
        tileX: number,
        tileY: number,
        target: { r: number; g: number; b: number },
      ): number {
        const image = context.getImageData(tileX * tileSize, tileY * tileSize, tileSize, tileSize);
        let count = 0;
        for (let index = 0; index < image.data.length; index += 4) {
          const distance =
            Math.abs(image.data[index] - target.r) +
            Math.abs(image.data[index + 1] - target.g) +
            Math.abs(image.data[index + 2] - target.b);
          if (distance < 90) {
            count += 1;
          }
        }
        return count;
      }

      return {
        enemyPixels: countColorNearTile(7, 4, enemyColor),
        playerPixels: countColorNearTile(2, 2, playerColor),
        playerOnEnemyTile: countColorNearTile(7, 4, playerColor),
        enemyOnPlayerTile: countColorNearTile(2, 2, enemyColor),
      };
    },
    { enemyColor: ENEMY_COLOR, playerColor: PLAYER_COLOR, tileSize: TILE_SIZE },
  );

  expect(visual.playerPixels).toBeGreaterThan(20);
  expect(visual.enemyPixels).toBeGreaterThan(20);
  expect(visual.playerOnEnemyTile).toBeLessThan(5);
  expect(visual.enemyOnPlayerTile).toBeLessThan(5);
});
