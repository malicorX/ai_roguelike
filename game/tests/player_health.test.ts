import { describe, expect, it } from "vitest";
import { createGame, stepGame } from "../src/engine";

describe("player health depletion", () => {
  it("reduces player and enemy health on collision with defensive array access", () => {
    const game = createGame({ seed: 1 });

    // Verify initial state explicitly before action
    expect(game.enemies.length).toBe(1);
    expect(game.enemies[0]?.hp).toBe(6);
    expect(game.player.hp).toBe(10);

    const nearEnemy = {
      ...game,
      player: { ...game.player, x: 6, y: 4 },
    };

    const hit = stepGame(nearEnemy, { type: "move", dx: 1, dy: 0 });

    // Verify after collision with defensive access patterns
    expect(hit.enemies.length).toBe(1);
    expect(hit.enemies[0]?.hp).toBe(3);
    expect(hit.player.hp).toBe(8);
    expect(hit.log).toContain("You hit enemy-1 for 3 damage.");
    expect(hit.log).toContain("enemy-1 hits you for 2 damage.");
  });

  it("handles multiple enemies with explicit initial state verification", () => {
    const game = createGame({ seed: 1 });

    // Create a state with two enemies adjacent to player's start position
    const multiEnemyState = {
      ...game,
      enemies: [
        { id: "enemy-1", x: 3, y: 2, hp: 6, attack: 2 },
        { id: "enemy-2", x: 4, y: 2, hp: 5, attack: 1 },
      ],
      player: { ...game.player, x: 2, y: 2 },
    };

    // Verify initial state explicitly before action
    expect(multiEnemyState.enemies.length).toBe(2);
    const enemy1 = multiEnemyState.enemies.find(e => e.id === "enemy-1");
    const enemy2 = multiEnemyState.enemies.find(e => e.id === "enemy-2");
    expect(enemy1?.hp).toBe(6);
    expect(enemy2?.hp).toBe(5);

    // Move player right to bump into enemy-1 at (3,2)
    const hit = stepGame(multiEnemyState, { type: "move", dx: 1, dy: 0 });

    // After collision, enemy-1 should have taken damage
    expect(hit.enemies.length).toBe(2);
    const hitEnemy1 = hit.enemies.find(e => e.id === "enemy-1");
    const hitEnemy2 = hit.enemies.find(e => e.id === "enemy-2");
    expect(hitEnemy1?.hp).toBe(3);
    expect(hitEnemy2?.hp).toBe(5);

    // Player should have taken damage from enemy-1's attack (2)
    expect(hit.player.hp).toBe(8);
  });

  it("handles enemy defeat and empty array access", () => {
    const game = createGame({ seed: 1 });
    const nearEnemy = {
      ...game,
      player: { ...game.player, x: 6, y: 4 },
    };

    // First hit to reduce enemy HP to 3
    const hit = stepGame(nearEnemy, { type: "move", dx: 1, dy: 0 });
    expect(hit.enemies.length).toBe(1);
    expect(hit.enemies[0]?.hp).toBe(3);

    // Second move to defeat enemy
    const defeated = stepGame(hit, { type: "move", dx: 1, dy: 0 });
    expect(defeated.enemies.length).toBe(0);
    // Ensure no unsafe access after array is empty - optional chaining returns undefined
    expect(defeated.enemies[0]?.hp).toBeUndefined();
  });
});
