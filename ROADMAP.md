# ai_roguelike — a self-developing roguelike browser game

**Repo:** github.com/malicorx/ai_roguelike · **Deploy:** theebie.de · **Compute:** sparky1 developer studio + sparky2 evaluation lab · **Local project dir:** `M:\Data\Projects\ai_rogue`

> **The clue:** after a one-time human bootstrap, the game designs, builds, tests, reviews, and improves *itself* — an endless loop of specialized LLM agents with **no human in the loop**, shipping continuously to theebie.de. You start it from PowerShell (`develop.ps1 --time 100h`) and walk away.

---

## 1. Principles (the rails that make hands-off autonomy safe)
These are non-negotiable — they are what let the loop run unattended without corrupting itself or the deploy:
- **No self-approval.** The agent that writes a change never approves it. A *different* agent reviews. (Same discipline that's been carrying the SAMI work.)
- **Green-gate everything.** Nothing merges unless the test suite passes; nothing deploys unless `main` is green *and* a post-deploy smoke test passes.
- **Always reversible.** Every deploy is rollback-able; the loop reverts its own bad commit automatically on a red smoke.
- **Bounded.** The loop stops at `--time`, an iteration cap, a token/cost budget, or a `STOP` file. It never runs truly forever without a ceiling.
- **Contained.** Agents get the repo + the deploy target and nothing else — no host shell, no secrets, no infra creds. (Hard-won lesson: unaudited host shells were the hole.)
- **Observable.** Every cycle logs its objective, diff, review verdicts, test results, visual evaluation, and deploy outcome. A dashboard shows the game evolving.

## 2. The studio (agent roles)
Each role is a prompt + tool profile. **sparky1** is the developer studio that owns repo writes, branches, implementation, review, integration, and deploy decisions. **sparky2** is the evaluation lab: it pulls candidate builds, runs the game, hunts bugs, measures playability/fun/balance, captures screenshots, and returns structured reports. A role can be one model or several competing.
- **Director / Planner** — reads backlog + playtest telemetry + game state, picks the next objective, sets priority. The only role that decides *what* to do next.
- **Idea Generator (game designer)** — proposes mechanics/content: procedural generation, items, enemies, biomes, progression, meta-loop, run modifiers.
- **Backend Designer/Engineer** — server state, persistence, save system, leaderboard/API (only if a feature needs it — v0 is client-only).
- **Frontend Designer/Engineer** — canvas/DOM rendering, input, UI/UX, art direction (ASCII or tiles), feel/juice.
- **Art Director** — owns the visual style guide, palette, readability rules, screenshot baselines, and style-drift review.
- **Implementer / Builder** — writes the code for the chosen objective on a feature branch. Never merges its own work.
- **Reviewer(s)** — code review + design review: correctness, no regressions, scope/fun. Blocks or approves.
- **Evaluator(s)** — sparky2 test agents that run automated tests, headless playthroughs, input fuzzing, screenshot capture, and visual/readability checks.
- **Player agent** — actually plays candidate builds and reports bugs, confusion, easy exploits, balance problems, and fun/friction notes.
- **Integrator** — merges green, reviewed branches to `main`; resolves conflicts.
- **Deployer** — builds, deploys to theebie, runs post-deploy smoke, auto-rolls-back on failure.
- **Historian / Curator** — maintains CHANGELOG, this roadmap, and a "design bible"; prunes dead ideas so the backlog stays coherent.

## 3. The loop (one cycle)
1. **Director** picks an objective (from backlog, or an **Idea Gen** proposal).
2. **Designer(s)** write a short spec.
3. **Builder** implements it on a feature branch.
4. **Reviewer(s)** review — rework until pass (no self-approval).
5. **sparky2 evaluation** pulls the candidate, runs tests/playthroughs/screenshots, and returns separate QA + design reports.
6. **Builder** reworks if sparky2 reports blocking issues; non-blocking design ideas go to backlog.
7. **Integrator** merges to `main` (green only).
8. **Deployer** ships to theebie + smoke-tests; rolls back on red.
9. **Historian** logs the cycle → back to step 1.

A cycle that fails any gate is **data**: it's logged, the branch is parked or reverted, and the Director learns from it — never force-pushed through.

## 4. The control script — `develop.ps1`
```
develop.ps1 --time 100h [--repo github.com/malicorx/ai_roguelike]
            [--deploy theebie] [--max-cycles N] [--models <role=model,...>]
```
- Boots the loop across sparky1 + sparky2, runs until the time budget elapses, `--max-cycles` is hit, or a `STOP` file appears.
- Checkpoints loop state each cycle; a restart resumes cleanly (idempotent).
- Assigns sparky1 developer-studio roles and sparky2 evaluation-lab roles to the local Ollama Agents-A1 model running on each box.
- Emits a per-cycle log + a live status the human can glance at.

## 5. Tech stack (v0 — the studio may evolve it later)
- **Game:** TypeScript + HTML5 canvas, with a deterministic core and test harness first. Use rot.js only when it clearly saves effort over small local primitives. Client-first — roguelikes run fully in the browser.
- **Backend:** none in v0. Add a thin service (saves/leaderboard) only when a feature demands it, served via the theebie stack.
- **Repo + CI:** `github.com/malicorx/ai_roguelike`; GitHub Actions runs the test suite as the **merge gate** and a smoke build.
- **Deploy:** static build → theebie.de (served like the existing static UIs); a `roguelike-smoke` check post-deploy.
- **Inference:** Ollama on both sparkies with `hf.co/InternScience/Agents-A1-Q4_K_M-GGUF:latest` as the local default. Use external Gemini/ChatGPT reviews as independent checkpoints, not as the unattended merge authority.
- **Visual quality:** readable stylized tiles, a fixed palette, deterministic screenshot scenarios, and a `VISUAL_STYLE.md` guide that sparky2 evaluates on every candidate.

## 6. Phases
- **Phase 0 — Bootstrap (the ONLY human-touched step).** Create the repo + CI + deploy pipeline, the loop harness (`develop.ps1` + role runners), sparky1/sparky2 working directories, and a minimal playable roguelike: a rendered map, player movement, FOV, one enemy, a death screen, visual style guide, and screenshot smoke. Then hands off.
- **Phase 1 — Loop online.** The studio runs and ships small, green-gated, deployed enhancements each cycle. Goal: prove the loop is **stable and reversible** over many unattended cycles.
- **Phase 2 — Depth.** Procedural dungeon generation, items/inventory, enemy variety + AI, progression, permadeath + a meta-loop. The agents grow the actual game.
- **Phase 3 — Polish + self-direction.** The Director sets its own goals from **playtest telemetry** and a "fun/quality" signal (a critic agent + the Player agent's reports); art and balance evolve from data.
- **Phase 4 — Open-ended.** Continuous self-improvement inside the rails; the human only reads the changelog and occasionally nudges direction.

## 7. Guardrails / stop conditions
- Time budget (`--time`), iteration cap, `STOP` file, token/cost budget.
- **Deploy gate:** `main` green + smoke green; automatic rollback on a red smoke.
- **Scope guard:** repo-only writes; no infra/secrets/deploy-credential access; contained runtime per agent.
- **Health watchdog** (mirror the fleet_health pattern): monitors the loop *and* the deployed game (build health, error rate, "is it still playable"); red → pause the loop and log.
- **Evaluation boundary:** sparky2 returns QA/design reports but does not write game code by default. sparky1 remains the only autonomous source-code writer.
- **Visual gate:** screenshot scenarios must preserve player/enemy/readability, UI clarity, palette coherence, and no blocking visual regressions.

## 8. Open questions (first Director cycle, or resolve at bootstrap)
- Stack: rot.js vs from-scratch engine? Any backend in v0 (probably no)?
- The **quality signal** the Director optimizes — playtest heuristics, a critic agent, crash/rage-quit telemetry from the Player agent?
- How competing ideas are arbitrated (Director decides, or a vote among reviewer agents?).
- Which visual metrics should block a merge versus become backlog?

## 9. What we already have to build on
The fleet reuses cleanly here: the multi-agent **build → review → test → merge → deploy** discipline is proven; the GitHub write access, the theebie deploy path, the sparky1/sparky2 local-inference stack, and the `fleet_health`-style watchdog all already exist. This project is that machine pointed at a game.
