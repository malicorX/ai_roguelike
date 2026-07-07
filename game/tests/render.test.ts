import { describe, expect, it } from "vitest";

import { createGame } from "../src/engine";
import { toGlyphGrid } from "../src/render";

describe("render snapshots", () => {
  it("converts v0 game state into a deterministic glyph grid", () => {
    const game = createGame({ seed: 1 });

    expect(toGlyphGrid(game)).toEqual([
      "############",
      "#..........#",
      "#.@........#",
      "#..........#",
      "#......E...#",
      "#..........#",
      "#..........#",
      "############",
    ]);
  });
});
