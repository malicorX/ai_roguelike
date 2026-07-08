from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CycleRecord:
    number: int
    objective: str
    branch: str
    commit: str
    director: str
    designer: str
    builder: str
    reviewer: dict[str, Any]
    proposal_lint: dict[str, Any]
    request: dict[str, Any]
    report: dict[str, Any]
    apply: dict[str, Any]
    merge: dict[str, Any]
    critic: dict[str, Any]
    blocked: bool
    blocking_reasons: list[str]
    mode: str
    roles_run: list[str]


@dataclass(frozen=True)
class PublishResult:
    devlog_index: Path
    docs_index: Path
    cycle_count: int


def load_cycles(state_dir: Path) -> list[CycleRecord]:
    cycle_numbers = sorted(_discover_cycle_numbers(state_dir))
    return [_load_cycle(state_dir, number) for number in cycle_numbers]


def publish_site(repo_root: Path, state_dir: Path, out_dir: Path) -> PublishResult:
    cycles = load_cycles(state_dir)
    devlog_dir = out_dir / "devlog"
    docs_dir = out_dir / "docs"
    artifacts_dir = devlog_dir / "artifacts"

    if devlog_dir.exists():
        shutil.rmtree(devlog_dir)
    if docs_dir.exists():
        shutil.rmtree(docs_dir)
    devlog_dir.mkdir(parents=True, exist_ok=True)
    docs_dir.mkdir(parents=True, exist_ok=True)
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    for cycle in cycles:
        _copy_cycle_artifacts(state_dir, artifacts_dir, cycle.number)
        (devlog_dir / f"cycle-{cycle.number:04d}.html").write_text(
            _render_cycle_page(cycle),
            encoding="utf-8",
        )

    devlog_index = devlog_dir / "index.html"
    docs_index = docs_dir / "index.html"
    devlog_index.write_text(_render_devlog_index(cycles), encoding="utf-8")
    docs_index.write_text(_render_docs_index(), encoding="utf-8")
    (docs_dir / "visual-style.html").write_text(
        _render_markdown_page(
            "Visual Style",
            _read_repo_doc(repo_root, "VISUAL_STYLE.md"),
            active="visual-style",
        ),
        encoding="utf-8",
    )
    (docs_dir / "studio.html").write_text(_render_studio_page(), encoding="utf-8")

    return PublishResult(devlog_index=devlog_index, docs_index=docs_index, cycle_count=len(cycles))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Publish static devlog and docs from studio cycle artifacts.")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--state-dir", type=Path, default=None)
    parser.add_argument("--out-dir", type=Path, default=None)
    args = parser.parse_args(argv)

    repo_root = args.repo_root
    state_dir = args.state_dir or repo_root / "studio" / "state"
    out_dir = args.out_dir or repo_root / "site"
    result = publish_site(repo_root, state_dir, out_dir)
    print(f"published devlog: {result.devlog_index} ({result.cycle_count} cycles)")
    print(f"published docs: {result.docs_index}")
    return 0


def _discover_cycle_numbers(state_dir: Path) -> set[int]:
    numbers: set[int] = set()
    if not state_dir.is_dir():
        return numbers
    for path in state_dir.glob("cycle-*-director.md"):
        match = re.match(r"cycle-(\d+)-director\.md$", path.name)
        if match:
            numbers.add(int(match.group(1)))
    return numbers


def _load_cycle(state_dir: Path, number: int) -> CycleRecord:
    prefix = f"cycle-{number:04d}"
    director = _read_text(state_dir / f"{prefix}-director.md")
    designer = _read_text(state_dir / f"{prefix}-designer.md")
    builder = _read_text(state_dir / f"{prefix}-builder.md")
    reviewer = _read_json(state_dir / f"{prefix}-reviewer.json")
    proposal_lint = _read_json(state_dir / f"{prefix}-proposal-lint.json")
    request = _read_json(state_dir / f"{prefix}-request.json")
    report = _read_json(state_dir / f"{prefix}-report.json")
    apply = _read_json(state_dir / f"{prefix}-apply.json")
    merge = _read_json(state_dir / f"{prefix}-merge.json")
    critic = _read_json(state_dir / f"{prefix}-critic.json")
    objective = str(request.get("objective") or _objective_from_director(director))
    mode = "write" if apply or merge or "write cycle" in str(request.get("spec", "")).lower() else "proposal"
    blocked, reasons = _cycle_status(proposal_lint, report, reviewer=reviewer, apply=apply, merge=merge)
    roles_run = _roles_run(director, designer, builder, reviewer, report)
    return CycleRecord(
        number=number,
        objective=objective,
        branch=str(merge.get("branch") or apply.get("branch") or request.get("branch", "unknown")),
        commit=str(merge.get("commit") or apply.get("commit") or request.get("commit", "unknown")),
        director=director,
        designer=designer,
        builder=builder,
        reviewer=reviewer,
        proposal_lint=proposal_lint,
        request=request,
        report=report,
        apply=apply,
        merge=merge,
        critic=critic,
        blocked=blocked,
        blocking_reasons=reasons,
        mode=mode,
        roles_run=roles_run,
    )


def _roles_run(
    director: str,
    designer: str,
    builder: str,
    reviewer: dict[str, Any],
    report: dict[str, Any],
) -> list[str]:
    roles: list[str] = []
    if director.strip():
        roles.append("director")
    if designer.strip():
        roles.append("designer")
    if builder.strip():
        roles.append("builder")
    if reviewer.get("verdict"):
        roles.append(f"reviewer:{reviewer.get('verdict')}")
    if report:
        roles.append("tester")
    return roles


def _cycle_status(
    proposal_lint: dict[str, Any],
    report: dict[str, Any],
    *,
    reviewer: dict[str, Any] | None = None,
    apply: dict[str, Any] | None = None,
    merge: dict[str, Any] | None = None,
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if proposal_lint.get("verdict") == "REWORK":
        reasons.append("Builder proposal lint failed.")
        reasons.extend(str(issue) for issue in proposal_lint.get("issues", []))
    if reviewer and reviewer.get("verdict") == "REWORK":
        reasons.append("Reviewer requested rework.")
        reasons.extend(str(issue) for issue in reviewer.get("issues", []))
    if not report:
        reasons.append("Evaluation report missing.")
        return True, reasons
    qa = report.get("qa", {})
    design = report.get("design", {})
    if qa.get("verdict") == "REWORK":
        reasons.append("QA requested rework.")
        reasons.extend(str(bug) for bug in qa.get("bugs", []))
    if design.get("verdict") == "BLOCK":
        reasons.append("Design report blocked the cycle.")
    if apply and apply.get("verdict") == "APPLIED" and not merge and not reasons:
        reasons.append("Write cycle applied but not merged.")
    return bool(reasons), reasons


def _copy_cycle_artifacts(state_dir: Path, artifacts_dir: Path, number: int) -> None:
    prefix = f"cycle-{number:04d}"
    for suffix in (
        "director.md",
        "designer.md",
        "builder.md",
        "reviewer.json",
        "proposal-lint.json",
        "request.json",
        "report.json",
        "apply.json",
        "merge.json",
        "critic.json",
        "run.log",
    ):
        source = state_dir / f"{prefix}-{suffix}"
        if source.is_file():
            shutil.copy2(source, artifacts_dir / f"{prefix}-{suffix}")


def _render_devlog_index(cycles: list[CycleRecord]) -> str:
    rows = []
    for cycle in reversed(cycles):
        status = "blocked" if cycle.blocked else "pass"
        phases = _cycle_phases(cycle)
        critic_cell = _critic_index_cell(cycle.critic)
        rows.append(
            "<tr>"
            f"<td><a href=\"./cycle-{cycle.number:04d}.html\">Cycle {cycle.number}</a></td>"
            f"<td><span class=\"status {status}\">{status}</span></td>"
            f"<td>{_esc(cycle.mode)}</td>"
            f"<td class=\"phase-cell critic-cell\">{critic_cell}</td>"
            f"<td class=\"phase-cell roles\">{_esc(', '.join(cycle.roles_run))}</td>"
            f"<td class=\"phase-cell\">{_esc(phases.sparky1)}</td>"
            f"<td class=\"phase-cell handoff\">{_esc(phases.handoff)}</td>"
            f"<td class=\"phase-cell\">{_esc(phases.sparky2)}</td>"
            f"<td>{_esc(cycle.objective)}</td>"
            f"<td><code>{_esc(cycle.branch)}@{_esc(cycle.commit)}</code></td>"
            "</tr>"
        )
    body = "\n".join(rows) if rows else "<tr><td colspan=\"10\">No studio cycles recorded yet.</td></tr>"
    return _page_shell(
        title="ai_roguelike devlog",
        active_nav="devlog",
        heading="Studio devlog",
        subtitle="Each cycle splits cleanly: sparky1 develops, a JSON handoff crosses the wire, sparky2 runs the test gates.",
        body=f"""
<section class="panel">
  <h2>Where work happens</h2>
  <div class="pipeline">
    <article class="pipeline-lane sparky1">
      <p class="lane-label">sparky1 · development</p>
      <p>Director picks the objective. Builder proposes or writes a diff. Proposal lint and (in write mode) git apply/merge all run on the studio machine.</p>
      <p class="lane-artifacts">Artifacts: <code>director.md</code>, <code>designer.md</code>, <code>builder.md</code>, <code>reviewer.json</code>, <code>proposal-lint.json</code>, <code>critic.json</code>, optional <code>apply.json</code> / <code>merge.json</code></p>
    </article>
    <article class="pipeline-lane handoff">
      <p class="lane-label">handoff · transport</p>
      <p>Not a third agent — just <code>scp</code> + <code>ssh</code>. sparky1 writes <code>request.json</code>, sparky2 returns <code>report.json</code>. Keeps evaluation on a clean checkout.</p>
      <p class="lane-note">Skip sparky2 entirely with <code>--evaluation-target local</code> (everything on one host).</p>
    </article>
    <article class="pipeline-lane sparky2">
      <p class="lane-label">sparky2 · playtesting &amp; gates</p>
      <p>Checks out the candidate branch/commit, runs <code>npm test</code>, <code>npm run build</code>, <code>npm run smoke</code>, and optional Art Director / Player roles when configured in <code>--models</code>.</p>
      <p class="lane-artifacts">Artifact: <code>report.json</code></p>
    </article>
  </div>
</section>
<section class="panel">
  <h2>Latest cycles</h2>
  <table>
    <thead>
      <tr><th>Cycle</th><th>Status</th><th>Mode</th><th>Critic</th><th>Roles</th><th>sparky1</th><th>Handoff</th><th>sparky2</th><th>Objective</th><th>Git</th></tr>
    </thead>
    <tbody>
      {body}
    </tbody>
  </table>
</section>
<section class="panel">
  <h2>How to read a cycle</h2>
  <ol>
    <li><strong>sparky1 · Director</strong> — chooses the objective.</li>
    <li><strong>sparky1 · Designer</strong> — writes acceptance criteria and in-scope files (soul: <code>roles/designer.md</code>).</li>
    <li><strong>sparky1 · Builder</strong> — proposal or unified diff from the Designer spec only.</li>
    <li><strong>sparky1 · Reviewer</strong> — PASS/REWORK gate before apply or sparky2 (soul: <code>roles/reviewer.md</code>).</li>
    <li><strong>sparky1 · Proposal lint</strong> — blocks invented paths and unknown test commands.</li>
    <li><strong>sparky1 · Cycle critic</strong> — scores the finished cycle (player-visible impact, mechanics, tests, scope) and sets the next-cycle constraint for Director.</li>
    <li><strong>sparky1 · Write path</strong> (optional) — apply diff on a feature branch, merge to <code>main</code> only after sparky2 passes.</li>
    <li><strong>Handoff</strong> — <code>request.json</code> copied to sparky2 (and branch pushed when not on <code>main</code>).</li>
    <li><strong>sparky2 · Evaluation</strong> — automated unit, build, browser smoke, plus optional Art Director / Player LLM roles; <code>report.json</code> copied back.</li>
  </ol>
  <p>Open a cycle page for the full artifact trail with machine labels on each section.</p>
</section>
""",
    )


@dataclass(frozen=True)
class CyclePhases:
    sparky1: str
    handoff: str
    sparky2: str


def _cycle_phases(cycle: CycleRecord) -> CyclePhases:
    sparky1_parts: list[str] = []
    if cycle.director.strip():
        sparky1_parts.append("Director")
    if cycle.designer.strip():
        sparky1_parts.append("Designer")
    if cycle.builder.strip():
        sparky1_parts.append("Builder")
    reviewer_verdict = str(cycle.reviewer.get("verdict", "")).strip()
    if reviewer_verdict:
        sparky1_parts.append(f"Reviewer {reviewer_verdict}")
    lint_verdict = str(cycle.proposal_lint.get("verdict", "")).strip()
    if lint_verdict:
        sparky1_parts.append(f"Lint {lint_verdict}")
    if cycle.apply:
        sparky1_parts.append(f"Apply {cycle.apply.get('verdict', '?')}")
    if cycle.merge:
        sparky1_parts.append(f"Merge {cycle.merge.get('verdict', '?')}")

    if cycle.request:
        branch = str(cycle.request.get("branch", "main"))
        if cycle.report:
            handoff = f"request → report ({branch})"
        else:
            handoff = f"request sent ({branch})"
    else:
        handoff = "—"

    if cycle.report:
        qa = cycle.report.get("qa", {})
        qa_verdict = str(qa.get("verdict", "?"))
        checks = qa.get("checks", [])
        design = cycle.report.get("design", {})
        design_verdict = str(design.get("verdict", "?"))
        eval_roles = design.get("evaluation_roles", {})
        role_bits: list[str] = []
        if isinstance(eval_roles, dict):
            for role_name, payload in eval_roles.items():
                if isinstance(payload, dict) and payload.get("verdict"):
                    role_bits.append(f"{role_name} {payload['verdict']}")
                elif role_name in {"art_director", "player"}:
                    role_bits.append(role_name)
        role_suffix = f" ({', '.join(role_bits)})" if role_bits else ""
        if checks:
            sparky2 = f"QA {qa_verdict}: {', '.join(str(check) for check in checks)} · Design {design_verdict}{role_suffix}"
        else:
            sparky2 = f"QA {qa_verdict} · Design {design_verdict}{role_suffix}"
    elif cycle.request and not cycle.blocking_reasons:
        sparky2 = "Awaiting report"
    else:
        sparky2 = "—"

    return CyclePhases(
        sparky1=" → ".join(sparky1_parts) if sparky1_parts else "—",
        handoff=handoff,
        sparky2=sparky2,
    )


def _render_cycle_page(cycle: CycleRecord) -> str:
    status = "blocked" if cycle.blocked else "pass"
    phases = _cycle_phases(cycle)
    lint_issues = cycle.proposal_lint.get("issues", [])
    qa = cycle.report.get("qa", {})
    design = cycle.report.get("design", {})
    apply = cycle.apply
    merge = cycle.merge
    critic_section = _render_critic_section(cycle)
    write_section = ""
    if apply or merge:
        write_section = f"""
<section class="panel">
  <h3>sparky1 · Write cycle</h3>
  <p>Mode: <strong>{_esc(cycle.mode)}</strong></p>
  {"<p>Apply verdict: <strong>" + _esc(str(apply.get("verdict", "n/a"))) + "</strong></p>" if apply else ""}
  {"<p>Merge verdict: <strong>" + _esc(str(merge.get("verdict", "n/a"))) + "</strong></p>" if merge else ""}
  {"<pre>" + _esc(json.dumps(apply, indent=2)) + "</pre>" if apply else ""}
  {"<pre>" + _esc(json.dumps(merge, indent=2)) + "</pre>" if merge else ""}
  {"<p><a href=\"./artifacts/cycle-" + f"{cycle.number:04d}" + "-apply.json\">apply artifact</a></p>" if apply else ""}
  {"<p><a href=\"./artifacts/cycle-" + f"{cycle.number:04d}" + "-merge.json\">merge artifact</a></p>" if merge else ""}
</section>
"""
    body = f"""
<section class="panel hero">
  <p><a href="./index.html">← Back to devlog</a></p>
  <h2>Cycle {cycle.number}</h2>
  <p class="lede">{_esc(cycle.objective)}</p>
  <p><span class="status {status}">{status}</span> <code>{_esc(cycle.branch)}@{_esc(cycle.commit)}</code> · {_esc(cycle.mode)}</p>
  {"<ul>" + "".join(f"<li>{_esc(reason)}</li>" for reason in cycle.blocking_reasons) + "</ul>" if cycle.blocking_reasons else ""}
</section>
<section class="panel">
  <h2>Cycle pipeline</h2>
  <div class="pipeline compact">
    <article class="pipeline-lane sparky1">
      <p class="lane-label">sparky1</p>
      <p>{_esc(phases.sparky1)}</p>
    </article>
    <article class="pipeline-lane handoff">
      <p class="lane-label">handoff</p>
      <p>{_esc(phases.handoff)}</p>
    </article>
    <article class="pipeline-lane sparky2">
      <p class="lane-label">sparky2</p>
      <p>{_esc(phases.sparky2)}</p>
    </article>
  </div>
</section>
<section class="grid two">
  <article class="panel">
    <h3>sparky1 · Director</h3>
    <pre>{_esc(cycle.director)}</pre>
    <p><a href="./artifacts/cycle-{cycle.number:04d}-director.md">raw artifact</a></p>
  </article>
  <article class="panel">
    <h3>sparky1 · Designer spec</h3>
    <pre>{_esc(cycle.designer) if cycle.designer.strip() else "—"}</pre>
    <p><a href="./artifacts/cycle-{cycle.number:04d}-designer.md">raw artifact</a></p>
  </article>
</section>
<section class="grid two">
  <article class="panel">
    <h3>sparky1 · Builder proposal</h3>
    <pre>{_esc(cycle.builder)}</pre>
    <p><a href="./artifacts/cycle-{cycle.number:04d}-builder.md">raw artifact</a></p>
  </article>
  <article class="panel">
    <h3>sparky1 · Reviewer gate</h3>
    <p>Verdict: <strong>{_esc(str(cycle.reviewer.get("verdict", "unknown")))}</strong></p>
    {"<ul>" + "".join(f"<li>{_esc(str(issue))}</li>" for issue in cycle.reviewer.get("issues", [])) + "</ul>" if cycle.reviewer.get("issues") else "<p>No reviewer issues.</p>" if cycle.reviewer.get("verdict") else "<p>Reviewer did not run.</p>"}
    <p><a href="./artifacts/cycle-{cycle.number:04d}-reviewer.json">raw artifact</a></p>
  </article>
</section>
<section class="grid two">
  <article class="panel">
    <h3>sparky1 · Proposal lint</h3>
    <p>Verdict: <strong>{_esc(str(cycle.proposal_lint.get("verdict", "unknown")))}</strong></p>
    {"<ul>" + "".join(f"<li>{_esc(str(issue))}</li>" for issue in lint_issues) + "</ul>" if lint_issues else "<p>No lint issues.</p>"}
    <p><a href="./artifacts/cycle-{cycle.number:04d}-proposal-lint.json">raw artifact</a></p>
  </article>
  <article class="panel">
    <h3>sparky1 → sparky2 · Handoff (request)</h3>
    <p class="lane-note">Transport only: <code>request.json</code> is copied to sparky2 before gates run.</p>
    <pre>{_esc(json.dumps(cycle.request, indent=2))}</pre>
    <p><a href="./artifacts/cycle-{cycle.number:04d}-request.json">raw artifact</a></p>
  </article>
</section>
<section class="panel">
  <h3>sparky2 · Evaluation report (gates)</h3>
  <p class="lane-note">Playtesting and automated gates run on sparky2 against the candidate commit; results return as <code>report.json</code>.</p>
  <p>QA verdict: <strong>{_esc(str(qa.get("verdict", "unknown")))}</strong> · Design verdict: <strong>{_esc(str(design.get("verdict", "unknown")))}</strong></p>
  <pre>{_esc(json.dumps(cycle.report, indent=2))}</pre>
  <p><a href="./artifacts/cycle-{cycle.number:04d}-report.json">raw artifact</a></p>
</section>
{critic_section}
{write_section}
"""
    return _page_shell(
        title=f"Cycle {cycle.number} · ai_roguelike devlog",
        active_nav="devlog",
        heading=f"Cycle {cycle.number}",
        subtitle="Director, Builder, lint, sparky2 report, and cycle critic scores for one studio cycle.",
        body=body,
    )


def _render_critic_section(cycle: CycleRecord) -> str:
    critic = cycle.critic
    if not critic:
        return """
<section class="panel">
  <h3>sparky1 · Cycle critic</h3>
  <p>No critic artifact for this cycle (published before cycle critic was enabled, or cycle did not finalize).</p>
</section>
"""
    scores = critic.get("scores", {})
    constraint = str(critic.get("next_cycle_constraint", "")).strip()
    source = str(critic.get("source", "unknown")).strip()
    score_rows = ""
    if isinstance(scores, dict) and scores:
        score_rows = "".join(
            "<tr>"
            f"<td>{_esc(_critic_dimension_label(str(name)))}</td>"
            f"<td><span class=\"critic-score\">{_esc(str(value))}/5</span></td>"
            f"<td><div class=\"critic-bar\"><span style=\"width:{_critic_bar_width(int(value))}%\"></span></div></td>"
            "</tr>"
            for name, value in scores.items()
            if str(name).strip()
        )
    scores_table = (
        f"<table class=\"critic-table\"><thead><tr><th>Dimension</th><th>Score</th><th></th></tr></thead><tbody>{score_rows}</tbody></table>"
        if score_rows
        else "<p>No scores recorded.</p>"
    )
    constraint_block = (
        f"<p><strong>Next-cycle constraint:</strong> {_esc(constraint)}</p>"
        if constraint
        else "<p>No next-cycle constraint recorded.</p>"
    )
    return f"""
<section class="panel">
  <h3>sparky1 · Cycle critic</h3>
  <p class="lane-note">Post-cycle scorecard (source: <code>{_esc(source)}</code>). Low scores steer the next Director objective.</p>
  {scores_table}
  {constraint_block}
  <p><a href="./artifacts/cycle-{cycle.number:04d}-critic.json">raw artifact</a></p>
</section>
"""


def _critic_index_cell(critic: dict[str, Any]) -> str:
    if not critic:
        return "—"
    scores = critic.get("scores", {})
    if not isinstance(scores, dict) or not scores:
        return "—"
    lowest_name = min(scores, key=lambda key: int(scores[key]))
    lowest_value = int(scores[lowest_name])
    label = _critic_dimension_label(str(lowest_name))
    return (
        f"<span class=\"critic-score low\">{lowest_value}/5</span> "
        f"<span class=\"critic-dim\">{_esc(label)}</span>"
    )


def _critic_dimension_label(name: str) -> str:
    return name.replace("_", " ")


def _critic_bar_width(score: int) -> int:
    clamped = max(0, min(5, score))
    return clamped * 20


def _render_docs_index() -> str:
    return _page_shell(
        title="ai_roguelike docs",
        active_nav="docs",
        heading="Game docs",
        subtitle="Living documentation for the playable build and the autonomous studio around it.",
        body="""
<section class="panel">
  <h2>Start here</h2>
  <ul class="doc-list">
    <li><a href="./studio.html">Studio architecture</a> — sparky1, sparky2, and the evaluation exchange.</li>
    <li><a href="./visual-style.html">Visual style</a> — readability rules and screenshot gates.</li>
    <li><a href="../index.html">Play the game</a> — current deployed v0 build.</li>
    <li><a href="../devlog/index.html">Studio devlog</a> — what the agents planned and tested each cycle.</li>
  </ul>
</section>
<section class="panel">
  <h2>v0 controls</h2>
  <p>Move with WASD or arrow keys. Bump enemies to attack. The HUD shows HP, turn count, and the latest log line.</p>
</section>
<section class="panel">
  <h2>Documentation policy</h2>
  <p>The Historian and Art Director roles maintain these docs as the game evolves. The devlog records operational cycles; this section records what the game <em>is</em>.</p>
</section>
""",
    )


def _render_studio_page() -> str:
    return _page_shell(
        title="Studio architecture · ai_roguelike docs",
        active_nav="docs",
        heading="Studio architecture",
        subtitle="How sparky1 develops, sparky2 evaluates, and theebie hosts blessed builds.",
        body="""
<section class="panel">
  <h2>Hosts</h2>
  <ul>
    <li><strong>sparky1</strong> — developer studio. Director and Builder run here. Write mode applies diffs on feature branches and merges on green evaluation.</li>
    <li><strong>sparky2</strong> — evaluation lab. Runs unit/build/smoke/visual gates and returns structured QA/design reports.</li>
    <li><strong>theebie.de</strong> — public runtime for the playable build, docs, and devlog.</li>
  </ul>
</section>
<section class="panel">
  <h2>Handoff (do you need it?)</h2>
  <p>The handoff is not a third AI role. It is file transfer between machines so sparky2 can test a clean checkout without sparky1 grading its own homework.</p>
  <ol>
    <li>sparky1 writes <code>cycle-####-request.json</code> (objective, branch, commit, spec).</li>
    <li>If the candidate is not on <code>main</code>, sparky1 pushes the feature branch.</li>
    <li><code>scp</code> copies the request to sparky2; <code>ssh</code> runs <code>eval_lab.evaluate_candidate</code>.</li>
    <li><code>scp</code> copies <code>cycle-####-report.json</code> back to sparky1.</li>
  </ol>
  <p>For a single-machine setup, use <code>--evaluation-target local</code> and the orchestrator runs the same gates on sparky1 — no cross-host copy.</p>
</section>
<section class="panel">
  <h2>Current phase</h2>
  <p>Phase 1 write mode is live: Builder diffs apply on feature branches, sparky2 evaluates the candidate, and green cycles merge to <code>main</code>.</p>
</section>
""",
    )


def _render_markdown_page(title: str, markdown: str, *, active: str) -> str:
    return _page_shell(
        title=f"{title} · ai_roguelike docs",
        active_nav="docs",
        heading=title,
        subtitle="Generated from repository documentation.",
        body=f'<section class="panel markdown">{_markdown_to_html(markdown)}</section>',
    )


def _page_shell(*, title: str, active_nav: str, heading: str, subtitle: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{_esc(title)}</title>
  <style>{_site_css()}</style>
</head>
<body>
  <header class="site-header">
    <div class="wrap">
      <p class="eyebrow">ai_roguelike</p>
      <nav>
        <a href="../index.html" class="{'active' if active_nav == 'game' else ''}">Play</a>
        <a href="../devlog/index.html" class="{'active' if active_nav == 'devlog' else ''}">Devlog</a>
        <a href="../docs/index.html" class="{'active' if active_nav == 'docs' else ''}">Docs</a>
      </nav>
    </div>
  </header>
  <main class="wrap">
    <section class="hero">
      <h1>{_esc(heading)}</h1>
      <p class="lede">{_esc(subtitle)}</p>
    </section>
    {body}
  </main>
</body>
</html>
"""


def _site_css() -> str:
    return """
body { margin: 0; font-family: Georgia, "Times New Roman", serif; background: #111; color: #e8e1d3; }
.wrap { max-width: 980px; margin: 0 auto; padding: 1.25rem; }
.site-header { border-bottom: 1px solid #3a342c; background: #171411; }
.site-header .wrap { display: flex; justify-content: space-between; align-items: center; gap: 1rem; }
.eyebrow { margin: 0; letter-spacing: 0.08em; text-transform: uppercase; font-size: 0.8rem; color: #b7aa93; }
nav a { color: #f3ead8; margin-left: 1rem; text-decoration: none; }
nav a.active, nav a:hover { color: #f6c453; }
.hero h1 { margin-bottom: 0.35rem; font-size: 2rem; }
.lede { color: #c8bcaa; max-width: 70ch; }
.panel { background: #1b1814; border: 1px solid #342e27; border-radius: 10px; padding: 1rem 1.1rem; margin: 1rem 0; }
.grid.two { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 1rem; }
table { width: 100%; border-collapse: collapse; }
th, td { text-align: left; padding: 0.55rem 0.35rem; border-bottom: 1px solid #342e27; vertical-align: top; }
pre { white-space: pre-wrap; word-break: break-word; background: #0f0d0b; padding: 0.8rem; border-radius: 8px; overflow-x: auto; }
code { font-family: Consolas, monospace; }
.status { display: inline-block; padding: 0.1rem 0.45rem; border-radius: 999px; font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.04em; }
.status.pass { background: #23452d; color: #b4f0c0; }
.status.blocked { background: #4d2323; color: #ffc1c1; }
.pipeline { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 0.85rem; }
.pipeline.compact .pipeline-lane { padding: 0.75rem; }
.pipeline-lane { border-radius: 8px; padding: 0.9rem; border: 1px solid #342e27; background: #14110e; }
.pipeline-lane.sparky1 { border-color: #4a5f3a; }
.pipeline-lane.handoff { border-color: #5a4d2b; }
.pipeline-lane.sparky2 { border-color: #3a4f66; }
.lane-label { margin: 0 0 0.35rem; font-size: 0.78rem; letter-spacing: 0.06em; text-transform: uppercase; color: #b7aa93; }
.lane-artifacts, .lane-note { font-size: 0.92rem; color: #c8bcaa; }
.phase-cell { font-size: 0.9rem; max-width: 16rem; }
.phase-cell.handoff { color: #d9c27a; }
.critic-cell { font-size: 0.88rem; max-width: 10rem; }
.critic-score { font-weight: bold; color: #f6c453; }
.critic-score.low { color: #ffb4b4; }
.critic-dim { color: #c8bcaa; }
.critic-table { margin: 0.75rem 0; }
.critic-bar { height: 0.55rem; background: #2a241d; border-radius: 999px; overflow: hidden; }
.critic-bar span { display: block; height: 100%; background: linear-gradient(90deg, #8b5a2b, #f6c453); }
.doc-list { line-height: 1.7; }
.markdown h2, .markdown h3 { margin-top: 1.2rem; }
.markdown ul { padding-left: 1.2rem; }
"""


def _markdown_to_html(markdown: str) -> str:
    lines = markdown.splitlines()
    parts: list[str] = []
    in_list = False
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if in_list:
                parts.append("</ul>")
                in_list = False
            continue
        if stripped.startswith("## "):
            if in_list:
                parts.append("</ul>")
                in_list = False
            parts.append(f"<h2>{_esc(stripped[3:])}</h2>")
            continue
        if stripped.startswith("# "):
            if in_list:
                parts.append("</ul>")
                in_list = False
            parts.append(f"<h1>{_esc(stripped[2:])}</h1>")
            continue
        if stripped.startswith("- "):
            if not in_list:
                parts.append("<ul>")
                in_list = True
            parts.append(f"<li>{_esc(stripped[2:])}</li>")
            continue
        if in_list:
            parts.append("</ul>")
            in_list = False
        parts.append(f"<p>{_esc(stripped)}</p>")
    if in_list:
        parts.append("</ul>")
    return "\n".join(parts)


def _objective_from_director(director: str) -> str:
    for line in director.splitlines():
        normalized = line.strip()
        for prefix in ("Objective:", "Next objective:", "OBJECTIVE:"):
            if normalized.startswith(prefix):
                return normalized[len(prefix) :].strip()
        if normalized:
            return normalized
    return "Unknown objective"


def _read_repo_doc(repo_root: Path, name: str) -> str:
    path = repo_root / name
    return path.read_text(encoding="utf-8") if path.is_file() else f"Missing documentation file: {name}"


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip() if path.is_file() else ""


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _esc(value: str) -> str:
    return html.escape(value, quote=True)


if __name__ == "__main__":
    sys.exit(main())
