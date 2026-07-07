# HOWTO_AI.md — Operating the fleet (for an AI operator)

> **ai_roguelike note:** this is the **shared fleet systems guide** (copied from the MoltWorld
> project — same sparky1/sparky2/theebie/GitHub infrastructure the roguelike studio runs on).
> The MoltWorld-specific references (ai_ai2ai, SAMI, fleet_health) are the existing tenants; the
> patterns and gotchas apply verbatim to ai_roguelike. The roguelike's own specifics — repo
> `github.com/malicorx/ai_roguelike`, its theebie serving path, its CI — are established in
> **Phase 0 bootstrap** (`docs/PHASE_0_BOOTSTRAP.md`) and appended here as they land.

> Purpose: everything you need to interact with **sparky1**, **sparky2**, **theebie.de**,
> **GitHub**, and the agent/inference stack — plus the **gotchas** that waste hours if you
> don't know them. Read the "Pitfalls" section first; it's the highest-value part.
>
> Secrets are NOT in this file. It says *where* credentials live, never their values.

---

## 1. Topology at a glance

| Host | Role | Reach it via | Inference |
|------|------|--------------|-----------|
| **sparky1** | Hub / baseline GPU box (DGX Spark GB10, 119 GB unified) | `ssh sparky1` (from the sandbox) | Ollama `:11434` (qwen3:14b + nomic-embed) **and** llama-server `:8081` (Agents-A1, sami) |
| **sparky2** | Second GPU box (DGX Spark GB10, 119 GB) | `ssh sparky2` (also `ssh sparky1 'ssh sparky2 …'`; internal IP `10.1.0.2`) | Ollama `:11435` (Agents-A1, tool-agents) **and** llama-server `:8081` (Agents-A1, sami) + shim `:8082` |
| **theebie** | Production world backend (`https://www.theebie.de`) | **Only from sparky1**: `ssh root@84.38.65.246` | n/a (calls the sparkies) |
| **cursorComputer** | Windows dev/hub machine | Reachable over SSH from the boxes; holds the M: working copies | n/a |

**Data-flow direction matters:** the sparkies + gateways connect **out** to theebie. theebie
**cannot** reach into the sparky LAN. sparky1 is the only host that can reach *both* boxes and
theebie — so any cross-box orchestration (fleet_health gather, speed test) runs on **sparky1**.

Git repos: **`ai_ai2ai`** (MoltWorld world backend), **`ai_selfaware`** (SAMI research agent), and
**`ai_roguelike`** (this project). Remotes = `github.com/malicorX/{ai2ai,ai_selfaware,ai_roguelike}`.

---

## 2. The sandbox ⇄ hosts: how you actually run things

You (the AI) run in an isolated Linux sandbox. You reach the fleet with `ssh sparky1` / `ssh sparky2`.
The user's Windows folders are **mounted** at M: and appear in the sandbox under a `/…/mnt/…` path.

### 2.1 Editing repo files
- **Use the `Read`/`Edit`/`Write` tools for M: files** (the true files). Do **not** trust
  `cat`/`grep` of M: paths from `bash` — the mount is **stale/truncated** for bash reads
  (you'll see a file that parses as a `SyntaxError` mid-line while the Edit tool sees it fine).
- Practical consequence: to get an edited M: file onto a box, you often **can't** `cat mnt/file | ssh`.
  Instead, develop **directly on the box's git checkout** and commit from there (see §4), or author
  the content yourself and write it on the box.

### 2.2 Running commands on hosts — three recurring traps
1. **Output swallowing on backgrounding.** `ssh host 'cmd & ... sleep N ...'` frequently returns
   *nothing*. Don't debug the command — split it: launch in one call, **verify in a separate call**.
2. **Heredoc / quoting hell through ssh.** `ssh host 'cat > f <<EOF … EOF'` with nested quotes,
   `'''`, `$(...)`, or JSON breaks constantly. **Fix:** write the script to a local sandbox file with
   a `cat > /tmp/x <<'PYEOF'` heredoc (quoted delimiter, in the *sandbox* — reliable), then
   `cat /tmp/x | ssh host 'cat > /tmp/x && python3 /tmp/x'`. This pattern is your friend for every
   multi-file / multi-quote edit.
3. **Build shell commands as argv lists, not strings.** When a Python script must call `curl`/`ssh`
   with embedded JSON, pass a **list** to `subprocess.run([...])` (no shell) — or `shlex.quote` each
   arg for a remote string. Lists avoid malformed-command-fails-silently bugs.
4. **The bash tool has a 45 s timeout cap.** Long operations (model loads, builds, benchmarks) must
   be launched detached (`nohup … &` / `setsid`) and **polled** in later calls.

---

## 3. Reaching each host in detail

### sparky1 / sparky2
- `ssh sparky1`, `ssh sparky2` work directly from the sandbox (key + `~/.ssh/config`; sparky2 = `10.1.0.2`).
- The SSH key for the boxes is `ai_selfaware/config/ssh/…` (user `malicor`). If a fresh sandbox can't
  connect, the key may need CRLF stripped (`sed -i 's/\r$//'`) or `chmod 600`.

### theebie (production)
- **No direct route from the sandbox.** Hop through sparky1: `ssh sparky1 'ssh root@84.38.65.246 "…"'`.
- Root login, key auth (sparky1's key). Port 22 open. It's a public vserver (`vserver-on.de`).
- HTTPS is public: `https://www.theebie.de` (the world API + `/ui/*` pages). `/ui/*` **redirects** →
  use `curl -L`.

---

## 4. Git & GitHub

- **Repos' remotes are SSH** (`git@github.com:malicorX/…`). The **sparky boxes' SSH key
  authenticates to GitHub as `malicorX` with push rights including `main`** — so the reliable way to
  land code is: **edit on a box's checkout → commit on the box → `git push origin main` from the box.**
- A fine-grained **PAT** also exists (stored in the operator's memory), `Contents:WRITE` on the repos,
  **no Pull-Requests permission** (can push branches, cannot open/merge PRs via API). The sandbox
  usually has no PAT; prefer the box-push path above.
- **RAILS:** never push to `main`, merge, or deploy **without an explicit per-action "go"** from the
  user (for autonomous ai_roguelike, "go" = the green-gate + reviewer-approval defined in the roadmap).
  When you land something, keep both boxes reconciled: `git fetch origin -q && git merge --ff-only origin/main`.
- **CI** runs on push to `main`; the merge gate is the test suite. (ai_ai2ai also has a STATUS.md
  test-count self-check — bump the baseline if you add backend tests there.)

---

## 5. Inference stack (Agents-A1, the no-think lane)

Two runtimes coexist per box; that's intentional, not a bug (see §5.4).

### 5.1 Ollama
- sparky1 `:11434`, sparky2 `:11435` (system `ollama.service`, models in `/usr/share/.ollama/models`).
- Serves the **tool-agents** (openclaw/hermes/copaw) + embeddings (`nomic-embed-text`).
- Speaks its **native** API (`/api/chat`, `/api/tags`, `/api/show`) **and** an OpenAI-compat one
  (`:PORT/v1/…`). Has `OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_KV_CACHE_TYPE=q8_0`, `KEEP_ALIVE=-1`.
- `OLLAMA_CONTEXT_LENGTH=32768` → Ollama **truncates** overlong prompts (fast, lossy).

### 5.2 llama-server (the no-think fix for Agents-A1)
- systemd **`a1-llama.service`** (root-installed) runs `~/a1-llama/start.sh` → llama-server on
  `0.0.0.0:8081`, serving Agents-A1 with `--chat-template-kwargs '{"enable_thinking":false}'`
  (the official Qwen3.5 hard switch: no `<think>` generated at all, unlike Ollama's unreliable
  `think:false`). OpenAI API only (`/v1/chat/completions`, `/v1/models`).
- **The binary is Ollama's bundled one:** `/usr/local/lib/ollama/llama-server` (already CUDA-built
  for GB10). To use the GPU it MUST have `GGML_BACKEND_PATH=/usr/local/lib/ollama/cuda_v13/libggml-cuda.so`
  (point at the **.so file**, not the dir) + `LD_LIBRARY_PATH=/usr/local/lib/ollama/cuda_v13:/usr/local/lib/ollama`.
  Without it → silent CPU fallback at ~2 tok/s.
- **Always pass `-fa on`** (flash attention). Without it, llama-server runs ~3× slower than Ollama on
  the same model. `--alias agents-a1` makes `/v1/models` report the name clients expect.
- Change config = edit `~/a1-llama/start.sh` + `pkill -f 'llama-server.*8081'`; systemd
  `Restart=always` reloads it (no sudo needed for the reload; the *install* needed sudo).
- Model loads take ~15–40 s (21 GB). Poll `/health` for `{"status":"ok"}` before hitting it.

### 5.3 Who's on what (current state)
- **SAMI** (both boxes) → llama-server `:8081/v1`. Clean no-think.
- **Tool-agents** (openclaw/hermes/copaw) → **Ollama** (fast there, no `<think>` leak). Their prompts
  reach 57–73 k tokens; llama-server processes the full prompt each step (~45 s) and times out, while
  Ollama masks it by truncating to 32 k. **Leave tool-agents on Ollama** unless you validate a fix.
- **The roguelike studio agents** can use either lane — pick the no-think llama-server `:8081` for
  clean structured output (design/code/review), fall back to Ollama for very long contexts.

### 5.4 "Does running both halve efficiency?" — no.
One GPU is **shared**, not split. Concurrent generations slow each other only *during overlap*
(bursty agents rarely collide); idle-but-loaded models cost memory, not compute; both models fit
(≈45 GB of 119 GB). The traps to avoid are model **swap-thrash** (both are pinned, so fine) and
**flash-attention being off** (fix in §5.2).

---

## 6. Deploying to theebie (prod) — the pattern

Backend **code is baked into the Docker image** (only data is volume-mounted), so any `backend/` or
`static/` change needs a **rebuild**, not a restart.

```bash
# from sparky1 (MoltWorld example — the roguelike gets its own compose/service in Phase 0):
ssh root@84.38.65.246 'cd /opt/ai_ai2ai && git fetch -q origin && git merge --ff-only origin/main \
  && nohup bash -c "set -a; . deployment/.env; . scripts/clawd/sparring_model.env; set +a; \
     docker compose -f deployment/docker-compose.sparky1.yml up -d --build backend" \
     > /tmp/deploy.log 2>&1 < /dev/null & echo launched'
# then poll /tmp/deploy.log (build ~2–3 min) and: curl -sL -o /dev/null -w '%{http_code}' https://www.theebie.de/<path>
```
Gotchas: a **failed build keeps the old container running** (safe, no downtime); **new HTTP routes
return 401** until whitelisted (theebie is default-deny); source any required env files first, or
compose errors on missing variables.

---

## 7. systemd `--user` services (loops, pollers)

- Over a non-interactive ssh, `systemctl --user …` fails ("Failed to connect to bus") unless you
  `export XDG_RUNTIME_DIR="/run/user/$(id -u)"` first.
- `--user` services get a **minimal PATH** — set `Environment=PATH=/usr/local/bin:/usr/bin:/bin` or
  `curl`/`ssh`/`bash` won't be found and calls fail silently.
- Unit files: `~/.config/systemd/user/*.service`; enable with `systemctl --user enable --now …`.

---

## 8. Pitfalls checklist (the "don't repeat these" list)

- [ ] M: files: read with the **Read tool**, not bash `cat` (mount is stale for bash).
- [ ] Long ops: **launch detached, poll separately** (45 s bash cap; ssh swallows backgrounded output).
- [ ] Multi-quote/multi-file edits on a box: **write local file → `cat | ssh 'cat > … && run'`**.
- [ ] Python calling curl/ssh: **argv lists**, not shell strings with embedded JSON.
- [ ] llama-server slow / on CPU: check `GGML_BACKEND_PATH` (the **.so file**) and `-fa on`.
- [ ] theebie change not showing: it needs a **`--build`** (code is baked), env files sourced.
- [ ] theebie route 401s: add to the public-route whitelist / middleware bypass.
- [ ] `systemctl --user` over ssh: set **`XDG_RUNTIME_DIR`**; set service **PATH**.
- [ ] Never push `main` / deploy prod without the project's approval gate (autonomous = the green-gate).
- [ ] After landing code: **reconcile both boxes** (`git merge --ff-only origin/main`).
