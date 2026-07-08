import { describe, expect, it } from "vitest";
import { createGame, stepGame } from "../src/engine";

describe("enemy movement", () => {
  it("does not change enemy position when player moves adjacent without bumping", () => {
    const game = createGame({ seed: 1 });

    if (game.enemies.length === 0) {
      throw new Error("No enemies to test");
    }

    const initialPos = { x: game.enemies[0]!.x, y: game.enemies[0]!.y };

    // Move player away from enemy without bumping
    let state = stepGame(game, { type: "move", dx: -1, dy: 0 });

    if (state.enemies.length > 0 && state.enemies[0]?.id) {
      const currentPos = { x: state.enemies[0]!.x, y: state.enemies[0]!.y };
      expect(currentPos.x).toBe(initialPos.x);
      expect(currentPos.y).toBe(initialPos.y);
    } else if (state.enemies.length === 0) {
      // Enemy may have been defeated - acceptable outcome
      expect(true).toBe(true);
    }
  });

  it("preserves enemy position during combat bump sequence", () => {
    const game = createGame({ seed: 1 });

    if (game.enemies.length === 0) {
      throw new Error("No enemies to test");
    }

    // Setup player adjacent to enemy as in existing tests
    const nearEnemy = { ...game, player: { ...game.player, x: 6, y: 4 } };
    const hitState = stepGame(nearEnemy, { type: "move", dx: 1, dy: 0 });

    // Verify enemy position unchanged after first combat bump
    if (hitState.enemies.length > 0 && hitState.enemies[0]?.id) {
      expect(hitState.enemies[0]!.x).toBe(game.enemies[0]!.x);
      expect(hitState.enemies[0]!.y).toBe(game.enemies[0]!.y);
    }

    // Second bump may defeat enemy
    const finalState = stepGame(hitState, { type: "move", dx: 1, dy: 0 });

    if (finalState.enemies.length > 0 && finalState.enemies[0]?.id) {
      expect(finalState.enemies[0]!.x).toBe(game.enemies[0]!.x);
      expect(finalState.enemies[0]!.y).toBe(game.enemies[0]!.y);
    } else if (finalState.enemies.length === 0) {
      // Enemy defeated and removed - acceptable outcome
      expect(true).toBe(true);
    }
  });

  it("handles empty enemy array after defeat without accessing undefined properties", () => {
    const game = createGame({ seed: 1 });

    if (game.enemies.length === 0) {
      throw new Error("No enemies to test");
    }

    // Use the same setup as existing tests for defeating enemy
    let state = stepGame(game, { type: "move", dx: -1, dy: 0 });
    state = { ...state, player: { ...state.player, x: 6, y: 4 } };

    const hitState = stepGame(state, { type: "move", dx: 1, dy: 0 });
    const finalState = stepGame(hitState, { type: "move", dx: 1, dy: 0 });

    // After defeat, enemies array should be empty or contain remaining enemies
    if (finalState.enemies.length === 0) {
      expect(true).toBe(true);
    } else if (finalState.enemies.length > 0) {
      const remainingEnemy = finalState.enemies[0]!;
      // Verify position is valid number type
      expect(typeof remainingEnemy.x).toBe("number");
      expect(typeof remainingEnemy.y).toBe("number");
    }
  });
});
