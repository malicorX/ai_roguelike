import { describe, expect, it } from "vitest";

import { createGameHarness } from "../src/testHarness";

describe("game test harness", () => {
  it("exposes deterministic snapshots and applies actions", () => {
    const harness = createGameHarness({ seed: 1 });

    expect(harness.snapshot()).toEqual({
      player: { hp: 10, x: 2, y: 2 },
      enemies: [{ attack: 2, hp: 6, id: "enemy-1", x: 7, y: 4 }],
      glyphGrid: [
        "############",
        "#..........#",
        "#.@........#",
        "#..........#",
        "#......E...#",
        "#..........#",
        "#..........#",
        "############",
      ],
      lastLog: "You enter the dungeon.",
      turn: 0,
    });

    harness.act({ type: "move", dx: 1, dy: 0 });

    expect(harness.snapshot()).toMatchObject({
      player: { hp: 10, x: 3, y: 2 },
      lastLog: "You move.",
      turn: 1,
    });
  });
});
