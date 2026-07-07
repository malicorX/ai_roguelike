# Visual Style Guide

This guide is the merge-time visual target for ai_roguelike. The game may evolve its look over time,
but candidate builds must preserve readability, coherence, and player trust.

## Direction

The v0 style is a readable, stylized 2D tile roguelike: crisp grid, restrained palette, high contrast
for gameplay-critical objects, and small animations that clarify state without hiding information.

Do not optimize for screenshot prettiness at the cost of playability. A good screen lets the player
immediately identify themselves, nearby threats, walkable space, pickups, health, and danger.

## Hard Rules

- The player must be the most immediately identifiable actor on the map.
- Enemy classes must be distinguishable by shape, color, or icon, not only by tooltip text.
- Walls, floors, doors, hazards, and pickups must remain visually distinct in normal and low-light FOV.
- UI state such as HP, death, and current objective must be readable without covering gameplay.
- Effects and animations must not obscure player position, enemy position, or damage feedback.
- Screenshots from deterministic seeds must not introduce style drift, broken proportions, missing assets, or unreadable contrast.

## v0 Constraints

- Use a limited palette until the Art Director explicitly expands it.
- Prefer simple canvas primitives or small tiles over generated freeform art.
- Keep tile dimensions consistent across map rendering, collision, hit feedback, and screenshots.
- Use deterministic rendering for test seeds so sparky2 can compare screenshots over time.
- Avoid asset generation in Phase 0 unless the output is validated for size, transparency, palette fit, and in-game readability.

## Screenshot Scenarios

sparky2 should capture and review at least these deterministic states for every candidate build:

- Start room with player, walls, floor, and visible exits.
- First enemy encounter.
- Player below 30 percent HP.
- Enemy hit/death feedback.
- Player death or restart screen.

Future scenarios should cover inventory, ranged attacks, status effects, shops, bosses, and biome-specific lighting.

## Automated Visual Smoke

The current Phase 0 visual gate is intentionally mechanical and deterministic:

- Boot the production browser build with Playwright.
- Read the deterministic start state through `window.__AI_ROGUELIKE_TEST__`.
- Sample the canvas tile regions for the player and first enemy.
- Block the candidate if player/enemy colors disappear, overlap the wrong tile, or become indistinguishable from the scene.

This is not a replacement for art direction. It is the first cheap guard against regressions where
the game still compiles but the player or enemy stops being readable.

## Review Checklist

Visual QA reports should separate blocking regressions from backlog ideas.

Blocking examples:
- Player blends into the floor or effects.
- Enemy or hazard is not readable before it can hurt the player.
- UI hides combat-critical information.
- New palette breaks contrast in FOV or darkness.
- Screenshot smoke shows missing assets, wrong scale, or console rendering errors.

Backlog examples:
- A screen is readable but bland.
- Animation could communicate impact better.
- Two enemy types are technically distinguishable but not memorable.
- The scene lacks juice after repeated play.

## External Review Prompt

When asking an outside model to critique visuals, provide the current `VISUAL_STYLE.md`, screenshot
set, and the feature objective. Ask for: readability blockers, style drift, UI clarity issues,
balance/fairness signals visible in the screen, and concrete improvement suggestions.
