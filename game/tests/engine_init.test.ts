import { describe, expect, it } from "vitest";

import { createGame } from "../src/engine";

describe("game initialization", () => {
  it("creates player at expected starting position", () => {
    const game = createGame({ seed: 1 });
    expect(game.player.x).toBe(2);
    expect(game.player.y).toBe(2);
    expect(game.player.hp).toBe(10);
    expect(game.player.attack).toBe(3);
  });

  it("creates map with correct dimensions", () => {
    const game = createGame({ seed: 1 });
    expect(game.map.width).toBe(12);
    expect(game.map.height).toBe(8);
  });

  it("validates initial health bounds without assuming regeneration mechanics", () => {
    const game = createGame({ seed: 1 });
    expect(game.player.hp).toBeGreaterThan(0);
    expect(game.player.hp).toBeLessThanOrEqual(10);
    expect(game.player.attack).toBeGreaterThan(0);
  });
});
