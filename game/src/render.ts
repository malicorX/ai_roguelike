import type { GameState, Tile } from "./engine";

const TILE_GLYPHS: Record<Tile, string> = {
  wall: "#",
  floor: ".",
};

export function toGlyphGrid(game: GameState): string[] {
  const rows = game.map.tiles.map((row) => row.map((tile) => TILE_GLYPHS[tile]));

  rows[game.player.y]![game.player.x] = "@";
  for (const enemy of game.enemies) {
    rows[enemy.y]![enemy.x] = "E";
  }

  return rows.map((row) => row.join(""));
}

const TILE_SIZE = 48; // Matches main.ts for coordinate consistency

export function drawProximityTethers(ctx: CanvasRenderingContext2D, game: GameState): void {
  const amberColor = "#ffbf00";
  const now = Date.now();

  game.enemies.forEach(enemy => {
    const distance = Math.abs(game.player.x - enemy.x) + Math.abs(game.player.y - enemy.y);

    if (distance <= 2 && distance > 0) {
      let baseWidth: number;
      switch (distance) {
        case 1:
          baseWidth = 8;
          break;
        case 2:
          baseWidth = 4;
          break;
        default:
          return;
      }

      const pulseAmount = Math.sin(now / 300) * 1.5;
      const lineWidth = Math.max(2, baseWidth + pulseAmount);

      ctx.strokeStyle = amberColor;
      ctx.lineWidth = lineWidth;
      ctx.lineCap = "round";

      const startX = game.player.x * TILE_SIZE + TILE_SIZE / 2;
      const startY = game.player.y * TILE_SIZE + TILE_SIZE / 2;
      const endX = enemy.x * TILE_SIZE + TILE_SIZE / 2;
      const endY = enemy.y * TILE_SIZE + TILE_SIZE / 2;

      ctx.beginPath();
      ctx.moveTo(startX, startY);
      ctx.lineTo(endX, endY);
      ctx.stroke();
    }
  });
}
