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
