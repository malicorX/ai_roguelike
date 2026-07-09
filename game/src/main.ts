import { createGame, stepGame, type GameAction, type GameState } from "./engine";
import { toGlyphGrid, drawProximityTethers } from "./render";
import { snapshotGame, type HarnessSnapshot } from "./testHarness";

declare global {
  interface Window {
    __AI_ROGUELIKE_TEST__?: {
      act(action: GameAction): HarnessSnapshot;
      snapshot(): HarnessSnapshot;
    };
  }
}

const TILE_SIZE = 48;
const COLORS = {
  background: "#10141f",
  wall: "#5f6f89",
  floor: "#20283a",
  player: "#f8e16c",
  enemy: "#ff6b6b",
  text: "#d7e1f0",
};

const canvas = requireElement(document.querySelector<HTMLCanvasElement>("#game"), "Missing game canvas element.");
const status = requireElement(document.querySelector<HTMLParagraphElement>("#status"), "Missing status element.");
const context = requireCanvasContext(canvas);

let game = createGame({ seed: 1 });
window.__AI_ROGUELIKE_TEST__ = {
  act(action: GameAction): HarnessSnapshot {
    game = stepGame(game, action);
    render(game);
    return snapshotGame(game);
  },
  snapshot(): HarnessSnapshot {
    return snapshotGame(game);
  },
};
render(game);

window.addEventListener("keydown", (event) => {
  const action = actionFromKey(event.key);
  if (!action) {
    return;
  }

  event.preventDefault();
  game = stepGame(game, action);
  render(game);
});

function actionFromKey(key: string): GameAction | null {
  switch (key) {
    case "ArrowUp":
    case "w":
    case "W":
      return { type: "move", dx: 0, dy: -1 };
    case "ArrowDown":
    case "s":
    case "S":
      return { type: "move", dx: 0, dy: 1 };
    case "ArrowLeft":
    case "a":
    case "A":
      return { type: "move", dx: -1, dy: 0 };
    case "ArrowRight":
    case "d":
    case "D":
      return { type: "move", dx: 1, dy: 0 };
    default:
      return null;
  }
}

function render(current: GameState): void {
  const glyphGrid = toGlyphGrid(current);

  context.fillStyle = COLORS.background;
  context.fillRect(0, 0, canvas.width, canvas.height);
  context.font = "32px Consolas, monospace";
  context.textAlign = "center";
  context.textBaseline = "middle";

  glyphGrid.forEach((row, y) => {
    [...row].forEach((glyph, x) => {
      drawTile(glyph, x, y);
    });
  });

  // Draw proximity tethers on top of tiles
  drawProximityTethers(context, current);

  status.textContent = `HP ${current.player.hp} | Turn ${current.turn} | ${current.log.at(-1) ?? ""}`;
}

function drawTile(glyph: string, x: number, y: number): void {
  const left = x * TILE_SIZE;
  const top = y * TILE_SIZE;

  context.fillStyle = glyph === "#" ? COLORS.wall : COLORS.floor;
  context.fillRect(left, top, TILE_SIZE, TILE_SIZE);

  if (glyph === "." || glyph === "#") {
    return;
  }

  context.fillStyle = glyph === "@" ? COLORS.player : COLORS.enemy;
  context.fillText(glyph, left + TILE_SIZE / 2, top + TILE_SIZE / 2);
}

function requireElement<TElement extends Element>(element: TElement | null, message: string): TElement {
  if (!element) {
    throw new Error(message);
  }

  return element;
}

function requireCanvasContext(element: HTMLCanvasElement): CanvasRenderingContext2D {
  const nextContext = element.getContext("2d");
  if (!nextContext) {
    throw new Error("Canvas 2D rendering is not available.");
  }

  return nextContext;
}
