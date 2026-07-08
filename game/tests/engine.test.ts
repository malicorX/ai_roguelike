import { describe, expect, it } from "vitest";

import { createGame, stepGame } from "../src/engine";

describe("roguelike engine", () => {
  it("creates a deterministic v0 room from a seed", () => {
    const first = createGame({ seed: 7 });
    const second = createGame({ seed: 7 });

    expect(first.map.width).toBe(12);
    expect(first.map.height).toBe(8);
    expect(first.player).toEqual({ id: "player", x: 2, y: 2, hp: 10, attack: 3 });
    expect(first.enemies).toEqual([{ id: "enemy-1", x: 7, y: 4, hp: 6, attack: 2 }]);
    expect(second).toEqual(first);
  });

  it("moves the player on floor tiles and blocks wall movement", () => {
    const game = createGame({ seed: 1 });

    const moved = stepGame(game, { type: "move", dx: 1, dy: 0 });
    expect(moved.player).toMatchObject({ x: 3, y: 2, hp: 10 });

    const nearNorthWall = {
      ...moved,
      player: { ...moved.player, y: 1 },
    };
    const blocked = stepGame(nearNorthWall, { type: "move", dx: 0, dy: -1 });
    expect(blocked.player).toMatchObject({ x: 3, y: 1, hp: 10 });
    expect(blocked.log.at(-1)).toEqual("The wall blocks your way.");
  });

  it("uses bump combat when the player moves into an enemy", () => {
    const game = createGame({ seed: 1 });
    const nearEnemy = {
      ...game,
      player: { ...game.player, x: 6, y: 4 },
    };

    const hit = stepGame(nearEnemy, { type: "move", dx: 1, dy: 0 });
    expect(hit.player).toMatchObject({ x: 6, y: 4, hp: 8 });
    expect(hit.enemies).toEqual([{ id: "enemy-1", x: 7, y: 4, hp: 3, attack: 2 }]);
    expect(hit.log).toContain("You hit enemy-1 for 3 damage.");
    expect(hit.log).toContain("enemy-1 hits you for 2 damage.");

    const defeated = stepGame(hit, { type: "move", dx: 1, dy: 0 });
    expect(defeated.enemies).toEqual([]);
    expect(defeated.log).toContain("enemy-1 dies.");
  });
  it("moves the player left on floor tiles", () => {
    const game = createGame({ seed: 1 });
    const moved = stepGame(game, { type: "move", dx: -1, dy: 0 });
    expect(moved.player).toMatchObject({ x: 1, y: 2, hp: 10 });
  });
  it("moves the player up on floor tiles", () => {
    const game = createGame({ seed: 1 });
    const moved = stepGame(game, { type: "move", dx: 0, dy: -1 });
    expect(moved.player).toMatchObject({ x: 2, y: 1, hp: 10 });
  });
  it("blocks movement when player is at left map edge", () => {
    const game = createGame({ seed: 1 });
    const nearLeftEdge = {
      ...game,
      player: { ...game.player, x: 0 },
    };
    const blocked = stepGame(nearLeftEdge, { type: "move", dx: -1, dy: 0 });
    expect(blocked.player).toMatchObject({ x: 0, y: 2, hp: 10 });
    expect(blocked.log.at(-1)).toEqual("The wall blocks your way.");
  });
  it("defeats enemy when moving into it after previous combat", () => {
    const game = createGame({ seed: 1 });
    // First, move player to adjacent position (as in existing test)
    const nearEnemy = { ...game, player: { ...game.player, x: 6, y: 4 } };
    const hit = stepGame(nearEnemy, { type: "move", dx: 1, dy: 0 });
    // Now move again to defeat enemy (since enemy hp reduced)
    const defeated = stepGame(hit, { type: "move", dx: 1, dy: 0 });
    expect(defeated.enemies).toEqual([]);
    expect(defeated.log).toContain("enemy-1 dies.");
  });
  it("calculates enemy damage correctly when player attacks with different attack values", () => {
    // Test case 1: Standard attack (player attack=3, enemy hp=6)
    const game = createGame({ seed: 7 });
    const nearEnemy = { ...game, player: { ...game.player, x: 6, y: 4 } };
    const hit = stepGame(nearEnemy, { type: "move", dx: 1, dy: 0 });
    
    // Verify enemy takes exactly 3 damage (player attack value)
    expect(hit.enemies[0].hp).toBe(3);
    expect(hit.log).toContain("You hit enemy-1 for 3 damage.");
    
    // Test case 2: Enemy with lower HP that can be defeated in one hit
    const game2 = createGame({ seed: 8 });
    // Manually create scenario where enemy has low HP
    const lowHpEnemy = { ...game2, enemies: [{ id: "enemy-1", x: 7, y: 4, hp: 2, attack: 2 }] };
    const nearLowHp = { ...lowHpEnemy, player: { ...lowHpEnemy.player, x: 6, y: 4 } };
    const hitLowHp = stepGame(nearLowHp, { type: "move", dx: 1, dy: 0 });
    
    // Verify enemy defeated and removed from array
    expect(hitLowHp.enemies).toEqual([]);
    expect(hitLowHp.log).toContain("enemy-1 dies.");
    
    // Test case 3: Enemy survives with remaining HP after attack
    const game3 = createGame({ seed: 9 });
    const highHpEnemy = { ...game3, enemies: [{ id: "enemy-1", x: 7, y: 4, hp: 10, attack: 2 }] };
    const nearHighHp = { ...highHpEnemy, player: { ...highHpEnemy.player, x: 6, y: 4 } };
    const hitHighHp = stepGame(nearHighHp, { type: "move", dx: 1, dy: 0 });
    
    // Verify enemy takes damage but survives with correct remaining HP
    expect(hitHighHp.enemies[0].hp).toBe(7);
    expect(hitHighHp.log).toContain("You hit enemy-1 for 3 damage.");
  });
});
