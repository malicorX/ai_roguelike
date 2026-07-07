export type Tile = "wall" | "floor";

export type Actor = {
  id: string;
  x: number;
  y: number;
  hp: number;
  attack: number;
};

export type GameMap = {
  width: number;
  height: number;
  tiles: Tile[][];
};

export type DiagnosticsLog = string[];
export type GameState = {
  seed: number;
  turn: number;
  map: GameMap;
  player: Actor;
  enemies: Actor[];
  log: string[];
  diagnostics: DiagnosticsLog;
};

export type MoveAction = {
  type: "move";
  dx: -1 | 0 | 1;
  dy: -1 | 0 | 1;
};

export type GameAction = MoveAction;

export function createGame({ seed }: { seed: number }): GameState {
  return {
    seed,
    turn: 0,
    map: createRoomMap(12, 8),
    player: { id: "player", x: 2, y: 2, hp: 10, attack: 3 },
    enemies: [{ id: "enemy-1", x: 7, y: 4, hp: 6, attack: 2 }],
    log: ["You enter the dungeon."],
    diagnostics: [],
  };
}

export function stepGame(game: GameState, action: GameAction): GameState {
  return movePlayer(game, action);
}

function logTurnDiagnostics(game: GameState): void {
  const diag = `Turn ${game.turn}: Player HP=${game.player.hp}, Pos=(${game.player.x},${game.player.y}), Enemies=${game.enemies.length}`;
  game.diagnostics.push(diag);
}
function createRoomMap(width: number, height: number): GameMap {
  return {
    width,
    height,
    tiles: Array.from({ length: height }, (_, y) =>
      Array.from({ length: width }, (_, x) => (x === 0 || y === 0 || x === width - 1 || y === height - 1 ? "wall" : "floor")),
    ),
  };
}

function movePlayer(game: GameState, action: MoveAction): GameState {
  const target = {
    x: game.player.x + action.dx,
    y: game.player.y + action.dy,
  };

  const enemy = game.enemies.find((candidate) => candidate.x === target.x && candidate.y === target.y);
  if (enemy) {
    return resolveBumpCombat(game, enemy);
  }

  if (getTile(game.map, target.x, target.y) === "wall") {
    return {
      ...game,
      turn: game.turn + 1,
      log: [...game.log, "The wall blocks your way."],
    };
  }

  return {
    ...game,
    turn: game.turn + 1,
    player: { ...game.player, ...target },
    log: [...game.log, "You move."],
  };
}

function resolveBumpCombat(game: GameState, enemy: Actor): GameState {
  const damagedEnemy = {
    ...enemy,
    hp: enemy.hp - game.player.attack,
  };

  const combatLog = [`You hit ${enemy.id} for ${game.player.attack} damage.`];
  if (damagedEnemy.hp <= 0) {
    return {
      ...game,
      turn: game.turn + 1,
      enemies: game.enemies.filter((candidate) => candidate.id !== enemy.id),
      log: [...game.log, ...combatLog, `${enemy.id} dies.`],
    };
  }

  return {
    ...game,
    turn: game.turn + 1,
    player: {
      ...game.player,
      hp: game.player.hp - damagedEnemy.attack,
    },
    enemies: game.enemies.map((candidate) => (candidate.id === enemy.id ? damagedEnemy : candidate)),
    log: [...game.log, ...combatLog, `${enemy.id} hits you for ${damagedEnemy.attack} damage.`],
  };
}

function getTile(map: GameMap, x: number, y: number): Tile {
  return map.tiles[y]?.[x] ?? "wall";
}
