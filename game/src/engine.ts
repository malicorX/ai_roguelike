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
  console.log(`Map generation seed: ${seed}`);
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

  // If repulsor beacon and not dead, handle push
  if (enemy.id === "repulsor-beacon" && damagedEnemy.hp > 0) {
    const dx = game.player.x - enemy.x;
    const dy = game.player.y - enemy.y;
    let moveDx = 0, moveDy = 0;
    if (Math.abs(dx) >= Math.abs(dy)) {
      moveDx = Math.sign(dx);
      moveDy = 0;
    } else {
      moveDx = 0;
      moveDy = Math.sign(dy);
    }
    const targetX = game.player.x + moveDx;
    const targetY = game.player.y + moveDy;

    const isWall = getTile(game.map, targetX, targetY) === "wall";
    const hasEntity = game.enemies.some(e => e.x === targetX && e.y === targetY);

    if (!isWall && !hasEntity) {
      return {
        ...game,
        turn: game.turn, // unchanged
        player: { ...game.player, x: targetX, y: targetY },
        enemies: game.enemies.map(e => e.id === enemy.id ? damagedEnemy : e),
        log: [...game.log, ...combatLog, `${enemy.id} repels you!`],
      };
    } else {
      return {
        ...game,
        turn: game.turn, // unchanged
        player: game.player,
        enemies: game.enemies.map(e => e.id === enemy.id ? damagedEnemy : e),
        log: [...game.log, ...combatLog, "The wall blocks your repulsion."],
      };
    }
  }

  // If phase shift anchor and not dead, check for safe swap
  if (enemy.id === "phase-shift-anchor" && damagedEnemy.hp > 0) {
    // Check collision safety for both positions before swapping
    const playerDestX = enemy.x;
    const playerDestY = enemy.y;
    const enemyDestX = game.player.x;
    const enemyDestY = game.player.y;

    const isPlayerDestWall = getTile(game.map, playerDestX, playerDestY) === "wall";
    const isEnemyDestWall = getTile(game.map, enemyDestX, enemyDestY) === "wall";

    // Check for other entities at destination tiles (excluding the current enemy being swapped)
    const hasEntityAtPlayerDest = game.enemies.some(e => e.id !== enemy.id && e.x === playerDestX && e.y === playerDestY);
    const hasEntityAtEnemyDest = game.enemies.some(e => e.id !== enemy.id && e.x === enemyDestX && e.y === enemyDestY);

    // If both destinations clear, perform swap and return early with swapped state
    if (!isPlayerDestWall && !isEnemyDestWall && !hasEntityAtPlayerDest && !hasEntityAtEnemyDest) {
      return {
        ...game,
        turn: game.turn + 1,
        player: { ...game.player, x: enemyDestX, y: enemyDestY }, // Player takes Enemy's position
        enemies: game.enemies.map(e => e.id === enemy.id ? { ...damagedEnemy, x: playerDestX, y: playerDestY } : e), // Enemy (damaged) takes Player's position
        log: [...game.log, ...combatLog, "Positions swapped!"],
      };
    }
    // If blocked, fall through to normal combat resolution
  }

  if (damagedEnemy.hp <= 0) {
    return {
      ...game,
      turn: game.turn + 1,
      enemies: game.enemies.filter(e => e.id !== enemy.id),
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
    enemies: game.enemies.map(e => e.id === enemy.id ? damagedEnemy : e),
    log: [...game.log, ...combatLog, `${enemy.id} hits you for ${damagedEnemy.attack} damage.`],
  };
}

function getTile(map: GameMap, x: number, y: number): Tile {
  return map.tiles[y]?.[x] ?? "wall";
}
