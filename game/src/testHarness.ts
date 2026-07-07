import { createGame, stepGame, type Actor, type GameAction, type GameState } from "./engine";
import { toGlyphGrid } from "./render";

export type HarnessSnapshot = {
  player: Pick<Actor, "hp" | "x" | "y">;
  enemies: Actor[];
  glyphGrid: string[];
  lastLog: string;
  turn: number;
};

export type GameHarness = {
  act(action: GameAction): HarnessSnapshot;
  snapshot(): HarnessSnapshot;
};

export function createGameHarness({ seed }: { seed: number }): GameHarness {
  let game = createGame({ seed });

  return {
    act(action: GameAction): HarnessSnapshot {
      game = stepGame(game, action);
      return snapshotGame(game);
    },
    snapshot(): HarnessSnapshot {
      return snapshotGame(game);
    },
  };
}

export function snapshotGame(game: GameState): HarnessSnapshot {
  return {
    player: {
      hp: game.player.hp,
      x: game.player.x,
      y: game.player.y,
    },
    enemies: game.enemies.map((enemy) => ({ ...enemy })),
    glyphGrid: toGlyphGrid(game),
    lastLog: game.log.at(-1) ?? "",
    turn: game.turn,
  };
}
