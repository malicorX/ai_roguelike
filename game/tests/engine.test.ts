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
});
