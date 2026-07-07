# Phase 0 — Bootstrap (the one human-seeded step)

> Goal of Phase 0: hand the studio a working, deployable, *already-playable* skeleton + the loop
> harness, so that when `develop.ps1 --time 100h` starts, cycle 1 has something real to improve and
> a green pipeline to ship through. After Phase 0, no human touches the code.
>
> Deliverables: (1) repo scaffold + CI + deploy, (2) a minimal playable roguelike, (3) `develop.ps1`
> + the orchestrator loop + role runners. Everything below is skeleton-level — the studio fills it in.

---

## 1. Repo layout (`github.com/malicorx/ai_roguelike`)
```
ai_roguelike/
  game/                 # the browser game (TypeScript + HTML5 canvas; rot.js for FOV/RNG/path)
    src/                #   engine, map gen, entities, render, input, browser test harness
    index.html
    tests/              #   unit tests (vitest)
    smoke/              #   Playwright browser boot/playability smoke
  studio/               # the autonomous dev loop (Python, runs on sparky1)
    orchestrator.py     #   the cycle loop
    role_runner.py      #   one role invocation = one model call + tools
    roles/              #   one prompt+profile per role (director.md, builder.md, reviewer.md, …)
    backlog.jsonl       #   objectives (director appends/prioritizes)
    state/              #   per-cycle checkpoints, logs, changelog
  eval_lab/              # sparky2-side evaluation request/response schemas + runners
    evaluate_candidate.py
    reports/
  .github/workflows/ci.yml   # test suite = merge gate + a smoke build
  deploy/               # theebie serving (static build → /ui/roguelike or its own vhost) + smoke
  develop.ps1           # the human-facing launcher (runs on cursorComputer)
  VISUAL_STYLE.md
  ROADMAP.md  HOWTO_AI.md  PHASE_0_BOOTSTRAP.md
```

## 2. `develop.ps1` — the launcher (runs on cursorComputer)
Thin: it kicks the loop off on **sparky1** (the hub that can reach both boxes + theebie) and streams status.
```powershell
param(
  [string]$Time = "100h",           # wall-clock budget
  [string]$Repo = "github.com/malicorx/ai_roguelike",
  [string]$Deploy = "theebie",
  [int]   $MaxCycles = 0,           # 0 = unlimited (time-bounded)
  [string]$Models = "director=agents-a1,builder=agents-a1,reviewer=agents-a1,art_director=agents-a1,player=agents-a1"
)
$ErrorActionPreference = "Stop"
$deadlineArgs = "--time $Time --max-cycles $MaxCycles --deploy $Deploy --models `"$Models`""

# Launch the loop DETACHED on sparky1 (survives this shell); write a STOP-able pidfile.
ssh sparky1 @"
  cd ~/ai_roguelike/studio
  export XDG_RUNTIME_DIR=/run/user/`$(id -u)
  nohup python3 orchestrator.py $deadlineArgs > ~/ai_roguelike/studio/state/loop.log 2>&1 < /dev/null &
  echo `$! > ~/ai_roguelike/studio/state/loop.pid
  echo "launched loop pid `$(cat ~/ai_roguelike/studio/state/loop.pid)"
"@

# Stream status until the budget elapses or the user Ctrl-C's (loop keeps running server-side).
Write-Host "Loop running on sparky1. Tailing status (Ctrl-C stops tailing, NOT the loop)."
Write-Host "To stop the loop:  ssh sparky1 'touch ~/ai_roguelike/studio/state/STOP'"
ssh sparky1 "tail -f ~/ai_roguelike/studio/state/loop.log"
```

## 3. `orchestrator.py` — the cycle loop (runs on sparky1)
```python
# pseudo-skeleton
def main(time_budget, max_cycles, deploy, models):
    deadline = now() + parse_duration(time_budget)   # "100h" -> seconds
    cycle = load_checkpoint()                          # resume-safe
    while now() < deadline and not stop_file() and (max_cycles == 0 or cycle.n < max_cycles):
        obj   = run_role("director", ctx=world_state() + backlog() + telemetry())   # pick objective
        spec  = run_role("designer", ctx=obj)                                        # short spec
        branch = git_new_branch(f"cycle-{cycle.n}-{slug(obj)}")
        diff  = run_role("builder",  ctx=spec, repo=branch, tools=[read, write, run_tests])
        # --- gates: no self-approval, green only ---
        for reviewer in ("reviewer_code", "reviewer_design"):     # different agent(s) than builder
            verdict = run_role(reviewer, ctx=diff)
            if verdict != "PASS":
                diff = run_role("builder", ctx=spec + verdict, repo=branch)   # rework, re-review
        if not run_tests(branch):        continue_as_data(cycle, "tests_red"); continue
        report = run_sparky2_evaluation(branch, obj, spec)
        if report.qa.verdict != "PASS":  continue_as_data(cycle, "qa_red", report); continue
        if report.visual.verdict == "BLOCK": continue_as_data(cycle, "visual_red", report); continue
        git_merge_to_main(branch)                                  # integrator (green only)
        if deploy: 
            ok = deploy_to_theebie(); 
            if not ok: rollback(); continue_as_data(cycle, "deploy_red"); continue
        run_role("historian", ctx=cycle_summary(obj, diff))       # changelog + prune backlog
        checkpoint(cycle.advance())
```
Key properties: **resume-safe** (checkpoint each cycle), **STOP-able** (a `state/STOP` file), a
failed gate is **logged as data** and the cycle is abandoned — never forced through.

## 4. `role_runner.py` — one role = one model call + tools
```python
def run_role(role, ctx, repo=None, tools=()):
    prompt = render(f"roles/{role}.md", ctx)                     # role prompt + the context
    model, base_url = resolve_model(role)                        # from --models; llama-server :8081 or Ollama
    out = chat(base_url, model, prompt)                          # OpenAI-compat call (no-think lane)
    return apply_tools(out, tools, repo)                         # builder/tester get read/write/run; others are pure text
```
- **Model routing:** default to Ollama with `hf.co/InternScience/Agents-A1-Q4_K_M-GGUF:latest` on
  both boxes. sparky1 runs developer-studio roles via `:11434`; sparky2 runs evaluation-lab roles
  via `:11435`. Only add llama-server/no-think routing later if Ollama output discipline becomes a
  repeated blocker.
- **Tool profiles:** builder/tester get repo read/write + `run_tests`; reviewers/director are
  read-only (text verdicts); deployer gets the theebie deploy recipe (HOWTO §6) — *nothing* gets host
  shell, secrets, or infra creds (containment).

## 5. The roles (`studio/roles/*.md`)
One markdown prompt each, defining voice + output contract:
`director`, `designer` (idea-gen), `frontend`, `backend`, `builder`, `reviewer_code`,
`reviewer_design`, `art_director`, `tester`, `player`, `integrator`, `deployer`, `historian`.
Each ends with a strict output contract (e.g. reviewer → `PASS` / `REWORK: <numbered issues>`;
builder → a unified diff; player → `{reached, deaths, bugs[], fun_notes[]}`).

## 6. Sparky2 evaluation protocol
sparky1 sends sparky2 an evaluation request containing: branch/build id, objective, spec, changed
files, deterministic seeds, and requested focus. sparky2 returns two reports:
- **QA report:** automated test status, browser console errors, crashes, repro steps, broken
  invariants, and `PASS` / `REWORK`.
- **Design report:** fun, readability, balance, dominant strategies, confusing moments, screenshot
  notes, and backlog suggestions. Design issues block only when they break the current objective or
  violate `VISUAL_STYLE.md` hard rules.

sparky2 does not write game code by default. Its job is to judge candidate builds hard and make
the feedback actionable for sparky1.

## 7. Gates (what "done" means each cycle)
- **Review gate:** ≥1 reviewer PASS, and the reviewer is never the builder (no self-approval).
- **Test gate:** unit suite green (vitest) + a Playwright smoke that boots the browser build and drives the exposed test harness.
- **Evaluation gate:** sparky2 QA report PASS; visual/design report has no blocking readability or
  style-guide violations.
- **Deploy gate:** `main` green → build → deploy to theebie → post-deploy smoke (page loads, game
  boots, no console errors) → **auto-rollback on red.**
- **Health watchdog:** a `fleet_health`-style check on the loop (is it advancing?) + the deployed
  game (is it up + playable?); red → pause + log.

## 8. CI + deploy (Phase 0 wiring)
- `ci.yml`: install → browser install → `npm test` → `npm run typecheck` → `npm run build` → `npm run smoke` on push/PR to `main`. This is the **merge gate**.
- Deploy: a `deploy/` script the **Deployer** role runs from sparky1 → theebie (static build served
  under theebie; add the route to the public whitelist per HOWTO §6/§8). Post-deploy `roguelike-smoke`.

## 9. The v0 game (minimal but real, so cycle 1 has something to improve)
A single screen: a rendered dungeon room, `@` player, arrow/WASD movement, FOV/lighting, one
wandering enemy, bump-to-attack, HP, and a death → restart. It includes a deterministic test harness
so sparky2 can drive turns, read state snapshots, capture screenshots, and compare visual quality.
Everything else (procgen, items, biomes, meta-progression, art) is what the studio *builds*.

## 10. Phase 0 checklist (human, once)
- [ ] Create `github.com/malicorx/ai_roguelike` + add the boxes' deploy key / confirm push rights.
- [ ] Provision `~/ai_roguelike` on sparky1 as the developer-studio checkout.
- [ ] Provision `~/ai_roguelike` on sparky2 as the evaluation-lab checkout.
- [ ] Provision `/opt/ai_roguelike` on theebie as the deploy/runtime directory.
- [ ] Scaffold `game/` (TypeScript + canvas), the v0 playable, `tests/` (unit), browser smoke, `ci.yml`.
- [ ] Add `VISUAL_STYLE.md` and deterministic screenshot scenarios.
- [ ] Wire the theebie serving path + `roguelike-smoke`.
- [ ] Land `studio/` — `orchestrator.py`, `role_runner.py`, the `roles/*.md`, checkpoint/STOP.
- [ ] Land `eval_lab/` — candidate request schema, sparky2 runner, QA/design report schema.
- [ ] Land `develop.ps1`.
- [ ] Dry-run: `develop.ps1 --time 30m --max-cycles 1` → confirm one full cycle merges + deploys + rolls back cleanly on an injected failure.
- [ ] Hand off: `develop.ps1 --time 100h`.
