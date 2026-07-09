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
    proposals: dict[str, Any]
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


def load_cycle(state_dir: Path, cycle_number: int) -> CycleRecord:
    return _load_cycle(state_dir, cycle_number)


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
    for pattern in ("cycle-*-director.md", "cycle-*-proposals.json"):
        for path in state_dir.glob(pattern):
            match = re.match(r"cycle-(\d+)-(?:director\.md|proposals\.json)$", path.name)
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
    proposals = _read_json(state_dir / f"{prefix}-proposals.json")
    objective = str(request.get("objective") or _objective_from_director(director) or _objective_from_proposals(proposals))
    mode = "proposal-board" if proposals and not request and not director.strip() else "write" if apply or merge or "write cycle" in str(request.get("spec", "")).lower() else "proposal"
    blocked, reasons = _cycle_status(proposal_lint, report, reviewer=reviewer, apply=apply, merge=merge, proposals=proposals)
    roles_run = _roles_run(director, designer, builder, reviewer, report, proposals)
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
        proposals=proposals,
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
    proposals: dict[str, Any],
) -> list[str]:
    roles: list[str] = []
    proposal_items = proposals.get("proposals", [])
    if not isinstance(proposal_items, list):
        proposal_items = []
    critique_items = proposals.get("critiques", [])
    if not isinstance(critique_items, list):
        critique_items = []
    for proposal in proposal_items:
        if isinstance(proposal, dict) and proposal.get("author_role"):
            roles.append(str(proposal["author_role"]))
    for critique in critique_items:
        if isinstance(critique, dict) and critique.get("author_role"):
            roles.append(f"{critique['author_role']}:{critique.get('verdict', '?')}")
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
    proposals: dict[str, Any] | None = None,
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if proposal_lint.get("verdict") == "REWORK":
        reasons.append("Builder proposal lint failed.")
        reasons.extend(str(issue) for issue in proposal_lint.get("issues", []))
    if reviewer and reviewer.get("verdict") == "REWORK":
        reasons.append("Reviewer requested rework.")
        reasons.extend(str(issue) for issue in reviewer.get("issues", []))
    if not report and proposals:
        proposal_issues = _proposal_board_issues(proposals)
        return bool(proposal_issues), proposal_issues
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


def _objective_from_proposals(proposals: dict[str, Any]) -> str:
    selected_id = str(proposals.get("selected_id", "")).strip()
    proposal_items = proposals.get("proposals", [])
    if not isinstance(proposal_items, list):
        return "Specialist proposal board"
    for proposal in proposal_items:
        if isinstance(proposal, dict) and proposal.get("id") == selected_id:
            title = str(proposal.get("title", "")).strip()
            return f"Proposal: {title}" if title else "Specialist proposal board"
    return "Specialist proposal board"


def _proposal_board_issues(proposals: dict[str, Any]) -> list[str]:
    selected_id = str(proposals.get("selected_id", "")).strip()
    proposal_items = proposals.get("proposals", [])
    critiques = proposals.get("critiques", [])
    issues: list[str] = []
    if not selected_id:
        issues.append("Proposal board did not select a proposal.")
    if not isinstance(proposal_items, list) or not proposal_items:
        issues.append("Proposal board did not include specialist proposals.")
    if isinstance(critiques, list):
        for critique in critiques:
            if isinstance(critique, dict) and str(critique.get("verdict", "")).upper() == "BLOCK":
                issues.append(f"{critique.get('author_role', 'critic')} blocked proposal board.")
    return issues


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
        "proposals.json",
        "proposals.md",
        "process.md",
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
      <p>Specialist agents pitch concepts, QA critiques them, Director selects the proposal, and Builder implements the accepted concept. Proposal lint and (in write mode) git apply/merge all run on the studio machine.</p>
      <p class="lane-artifacts">Artifacts: <code>proposals.json</code>, <code>proposals.md</code>, <code>director.md</code>, <code>designer.md</code>, <code>builder.md</code>, <code>reviewer.json</code>, <code>proposal-lint.json</code>, <code>critic.json</code>, optional <code>apply.json</code> / <code>merge.json</code></p>
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
    <li><strong>sparky1 · Specialists</strong> — Enemy Designer, Systems Designer, and Art Director pitch concepts; QA Critic reviews them before code.</li>
    <li><strong>sparky1 · Director</strong> — chooses the accepted proposal to advance.</li>
    <li><strong>sparky1 · Designer</strong> — writes acceptance criteria and in-scope files from the selected proposal (soul: <code>roles/designer.md</code>).</li>
    <li><strong>sparky1 · Builder</strong> — implements the accepted proposal from the Designer spec.</li>
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
    proposal_items = cycle.proposals.get("proposals", [])
    if isinstance(proposal_items, list) and proposal_items:
        sparky1_parts.append("Proposal board")
    critique_items = cycle.proposals.get("critiques", [])
    if isinstance(critique_items, list):
        for critique in critique_items:
            if isinstance(critique, dict) and critique.get("verdict"):
                sparky1_parts.append(f"{critique.get('author_role', 'critic')} {critique.get('verdict')}")
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
    overview = _render_cycle_overview(cycle, phases)
    proposal_fold = _fold(
        "Phase 1 · Specialist proposals",
        _proposal_fold_summary(cycle),
        _render_proposal_body(cycle),
    )
    director_fold = _fold(
        "Phase 2 · Director selection",
        _director_fold_summary(cycle),
        _render_director_body(cycle),
    )
    designer_fold = _fold(
        "Phase 3 · Designer spec",
        _designer_fold_summary(cycle),
        _render_designer_body(cycle),
    )
    builder_fold = _fold(
        "Phase 4 · Builder implementation",
        _builder_fold_summary(cycle),
        _render_builder_body(cycle, lint_issues),
    )
    reviewer_fold = _fold(
        "Phase 5 · Reviewer gate",
        _reviewer_fold_summary(cycle),
        _render_reviewer_body(cycle),
    )
    evaluation_fold = _fold(
        "Phase 6 · sparky2 evaluation",
        _evaluation_fold_summary(cycle),
        _render_evaluation_body(cycle, qa, design),
    )
    handoff_fold = _fold(
        "Handoff request",
        _handoff_fold_summary(cycle),
        f'<pre>{_esc(json.dumps(cycle.request, indent=2))}</pre><p><a href="./artifacts/cycle-{cycle.number:04d}-request.json">raw artifact</a></p>',
        open_by_default=False,
    )
    critic_fold = _fold(
        "Cycle critic scores",
        _critic_fold_summary(cycle),
        _render_critic_body(cycle),
        open_by_default=False,
    )
    write_fold = ""
    if apply or merge:
        write_fold = _fold(
            "Apply, merge, deploy",
            _write_fold_summary(cycle),
            _render_write_body(cycle, apply, merge),
            open_by_default=False,
        )
    body = f"""
<section class="panel hero compact-hero">
  <p><a href="./index.html">← Back to devlog</a></p>
  <h2>Cycle {cycle.number}</h2>
  <p class="lede">{_esc(cycle.objective)}</p>
  <p><span class="status {status}">{status}</span> <code>{_esc(cycle.branch)}@{_esc(cycle.commit)}</code> · {_esc(cycle.mode)}</p>
</section>
{overview}
<section class="panel">
  <h2>Pipeline</h2>
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
{proposal_fold}
{director_fold}
{designer_fold}
{builder_fold}
{reviewer_fold}
{evaluation_fold}
{handoff_fold}
{critic_fold}
{write_fold}
<p class="artifact-links"><a href="./artifacts/cycle-{cycle.number:04d}-process.md">Full process report (markdown)</a></p>
"""
    return _page_shell(
        title=f"Cycle {cycle.number} · ai_roguelike devlog",
        active_nav="devlog",
        heading=f"Cycle {cycle.number}",
        subtitle="Overview first, then expand any phase for the full agent artifacts.",
        body=body,
    )


def _fold(title: str, summary: str, body: str, *, open_by_default: bool = True) -> str:
    open_attr = " open" if open_by_default else ""
    return f"""
<details class="fold"{open_attr}>
  <summary><span class="fold-title">{_esc(title)}</span><span class="fold-hint">{_esc(summary)}</span></summary>
  <div class="fold-body">{body}</div>
</details>
"""


def _render_cycle_overview(cycle: CycleRecord, phases: CyclePhases) -> str:
    selected = _selected_proposal_label(cycle)
    game_impact = _game_impact_line(cycle)
    blocker = _primary_blocker(cycle)
    rows = [
        f"<li><strong>Outcome:</strong> {_esc(_outcome_label(cycle))}</li>",
        f"<li><strong>Selected concept:</strong> {_esc(selected)}</li>",
        f"<li><strong>Playable game:</strong> {_esc(game_impact)}</li>",
        f"<li><strong>Pipeline:</strong> {_esc(phases.sparky1)}</li>",
    ]
    if blocker:
        rows.append(f"<li><strong>Stopped because:</strong> {_esc(blocker)}</li>")
    if cycle.blocking_reasons:
        reason_items = "".join(f"<li>{_esc(reason)}</li>" for reason in cycle.blocking_reasons[:4])
        extra = len(cycle.blocking_reasons) - 4
        if extra > 0:
            reason_items += f"<li>…and {extra} more (expand Reviewer / Evaluation below)</li>"
        rows.append(f"<li><strong>Details:</strong><ul class=\"overview-sublist\">{reason_items}</ul></li>")
    return f"""
<section class="panel overview">
  <h2>At a glance</h2>
  <ul class="overview-list">{''.join(rows)}</ul>
</section>
"""


def _outcome_label(cycle: CycleRecord) -> str:
    if str(cycle.merge.get("verdict", "")).upper() == "MERGED":
        return "Merged and deployed"
    if cycle.blocked:
        reviewer = str(cycle.reviewer.get("verdict", "")).upper()
        if reviewer == "REWORK":
            return "Blocked at reviewer gate"
        qa = str(cycle.report.get("qa", {}).get("verdict", "")).upper()
        if qa == "REWORK":
            return "Blocked at evaluation"
        if cycle.proposals and not cycle.director.strip():
            return "Blocked at proposal board"
        return "Blocked before deploy"
    return "Completed"


def _game_impact_line(cycle: CycleRecord) -> str:
    if str(cycle.merge.get("verdict", "")).upper() == "MERGED":
        return "Updated on theebie — open Play to try it"
    if cycle.mode == "proposal-board":
        return "No code written (proposal-only cycle)"
    if cycle.blocked:
        return "No change — code never merged or deployed"
    return "Check merge/deploy artifacts"


def _primary_blocker(cycle: CycleRecord) -> str:
    if cycle.blocking_reasons:
        return cycle.blocking_reasons[0]
    return ""


def _selected_proposal_label(cycle: CycleRecord) -> str:
    proposals = cycle.proposals
    if not proposals:
        return cycle.objective or "—"
    selected_id = str(proposals.get("selected_id", "")).strip()
    items = proposals.get("proposals", [])
    if not isinstance(items, list):
        return selected_id or cycle.objective or "—"
    for item in items:
        if isinstance(item, dict) and item.get("id") == selected_id:
            title = str(item.get("title", "")).strip()
            role = str(item.get("author_role", "")).strip()
            return f"{title} ({role})" if title else selected_id
    return selected_id or cycle.objective or "—"


def _proposal_fold_summary(cycle: CycleRecord) -> str:
    proposals = cycle.proposals
    if not proposals:
        return "No proposal board"
    items = proposals.get("proposals", [])
    critiques = proposals.get("critiques", [])
    pitch_count = len(items) if isinstance(items, list) else 0
    qa_verdict = "?"
    if isinstance(critiques, list):
        for critique in critiques:
            if isinstance(critique, dict) and critique.get("author_role") == "qa_critic":
                qa_verdict = str(critique.get("verdict", "?"))
    return f"{pitch_count} pitches · QA {qa_verdict} · selected {_selected_proposal_label(cycle)}"


def _director_fold_summary(cycle: CycleRecord) -> str:
    if not cycle.director.strip():
        return "Did not run"
    objective = _objective_from_director(cycle.director) or cycle.objective
    return objective[:100] + ("…" if len(objective) > 100 else "")


def _designer_fold_summary(cycle: CycleRecord) -> str:
    if not cycle.designer.strip():
        return "Did not run"
    return "Spec written — expand for files and acceptance criteria"


def _builder_fold_summary(cycle: CycleRecord) -> str:
    if not cycle.builder.strip():
        return "Did not run"
    lint = str(cycle.proposal_lint.get("verdict", "?"))
    return f"Lint {lint} — expand for patches and summary"


def _reviewer_fold_summary(cycle: CycleRecord) -> str:
    verdict = str(cycle.reviewer.get("verdict", "")).strip() or "did not run"
    issues = cycle.reviewer.get("issues", [])
    if isinstance(issues, list) and issues:
        return f"{verdict} — {issues[0]}"
    return verdict


def _evaluation_fold_summary(cycle: CycleRecord) -> str:
    if not cycle.report:
        return "No evaluation report"
    qa = str(cycle.report.get("qa", {}).get("verdict", "?"))
    design = str(cycle.report.get("design", {}).get("verdict", "?"))
    return f"QA {qa} · Design {design}"


def _handoff_fold_summary(cycle: CycleRecord) -> str:
    if not cycle.request:
        return "No handoff"
    return f"{cycle.request.get('branch', 'main')} @ {cycle.request.get('commit', '?')}"


def _critic_fold_summary(cycle: CycleRecord) -> str:
    scores = cycle.critic.get("scores", {})
    if not isinstance(scores, dict) or not scores:
        return "No scores"
    lowest = min(scores, key=lambda key: int(scores[key]))
    return f"Lowest: {_critic_dimension_label(str(lowest))} {scores[lowest]}/5"


def _write_fold_summary(cycle: CycleRecord) -> str:
    merge = str(cycle.merge.get("verdict", "not merged"))
    apply = str(cycle.apply.get("verdict", "n/a")) if cycle.apply else "n/a"
    return f"Apply {apply} · Merge {merge}"


def _render_director_body(cycle: CycleRecord) -> str:
    if not cycle.director.strip():
        return "<p>Director did not run.</p>"
    return f'<pre>{_esc(cycle.director)}</pre><p><a href="./artifacts/cycle-{cycle.number:04d}-director.md">raw artifact</a></p>'


def _render_designer_body(cycle: CycleRecord) -> str:
    if not cycle.designer.strip():
        return "<p>Designer did not run.</p>"
    return f'<pre>{_esc(cycle.designer)}</pre><p><a href="./artifacts/cycle-{cycle.number:04d}-designer.md">raw artifact</a></p>'


def _render_builder_body(cycle: CycleRecord, lint_issues: list[Any]) -> str:
    if not cycle.builder.strip():
        return "<p>Builder did not run.</p>"
    lint = cycle.proposal_lint.get("verdict", "unknown")
    issues_html = (
        "<ul>" + "".join(f"<li>{_esc(str(issue))}</li>" for issue in lint_issues) + "</ul>"
        if lint_issues
        else "<p>No lint issues.</p>"
    )
    return (
        f"<p>Proposal lint: <strong>{_esc(str(lint))}</strong></p>{issues_html}"
        f'<pre>{_esc(cycle.builder)}</pre>'
        f'<p><a href="./artifacts/cycle-{cycle.number:04d}-builder.md">raw artifact</a> · '
        f'<a href="./artifacts/cycle-{cycle.number:04d}-proposal-lint.json">lint json</a></p>'
    )


def _render_reviewer_body(cycle: CycleRecord) -> str:
    verdict = str(cycle.reviewer.get("verdict", "")).strip()
    if not verdict:
        return "<p>Reviewer did not run.</p>"
    issues = cycle.reviewer.get("issues", [])
    issues_html = (
        "<ul>" + "".join(f"<li>{_esc(str(issue))}</li>" for issue in issues) + "</ul>"
        if isinstance(issues, list) and issues
        else "<p>No reviewer issues.</p>"
    )
    return (
        f"<p>Verdict: <strong>{_esc(verdict)}</strong></p>{issues_html}"
        f'<p><a href="./artifacts/cycle-{cycle.number:04d}-reviewer.json">raw artifact</a></p>'
    )


def _render_evaluation_body(cycle: CycleRecord, qa: dict[str, Any], design: dict[str, Any]) -> str:
    if not cycle.report:
        return "<p>No evaluation report.</p>"
    return (
        f'<p>QA verdict: <strong>{_esc(str(qa.get("verdict", "unknown")))}</strong> · '
        f'Design verdict: <strong>{_esc(str(design.get("verdict", "unknown")))}</strong></p>'
        f'<pre>{_esc(json.dumps(cycle.report, indent=2))}</pre>'
        f'<p><a href="./artifacts/cycle-{cycle.number:04d}-report.json">raw artifact</a></p>'
    )


def _render_write_body(cycle: CycleRecord, apply: dict[str, Any], merge: dict[str, Any]) -> str:
    parts = [f"<p>Mode: <strong>{_esc(cycle.mode)}</strong></p>"]
    if apply:
        parts.append(f"<p>Apply verdict: <strong>{_esc(str(apply.get('verdict', 'n/a')))}</strong></p>")
        parts.append(f"<pre>{_esc(json.dumps(apply, indent=2))}</pre>")
        parts.append(f'<p><a href="./artifacts/cycle-{cycle.number:04d}-apply.json">apply artifact</a></p>')
    if merge:
        parts.append(f"<p>Merge verdict: <strong>{_esc(str(merge.get('verdict', 'n/a')))}</strong></p>")
        parts.append(f"<pre>{_esc(json.dumps(merge, indent=2))}</pre>")
        parts.append(f'<p><a href="./artifacts/cycle-{cycle.number:04d}-merge.json">merge artifact</a></p>')
    return "".join(parts)


def _render_critic_body(cycle: CycleRecord) -> str:
    critic = cycle.critic
    if not critic:
        return "<p>No critic artifact for this cycle.</p>"
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
        f"<p><strong>Next-cycle constraint:</strong> {_esc(constraint)}</p>" if constraint else ""
    )
    return (
        f"<p class=\"lane-note\">Source: <code>{_esc(source)}</code></p>{scores_table}{constraint_block}"
        f'<p><a href="./artifacts/cycle-{cycle.number:04d}-critic.json">raw artifact</a></p>'
    )


def _render_proposal_body(cycle: CycleRecord) -> str:
    proposals = cycle.proposals
    if not proposals:
        return "<p>No proposal board artifact for this cycle.</p>"
    selected_id = str(proposals.get("selected_id", "")).strip()
    proposal_items = proposals.get("proposals", [])
    critique_items = proposals.get("critiques", [])
    if not isinstance(proposal_items, list):
        proposal_items = []
    if not isinstance(critique_items, list):
        critique_items = []
    proposal_rows = "".join(
        "<tr>"
        f"<td>{_esc(str(item.get('id', '')))}</td>"
        f"<td>{_esc(str(item.get('author_role', '')))}</td>"
        f"<td>{_esc(str(item.get('title', '')))}</td>"
        f"<td>{_esc(str(item.get('supports') or '—'))}</td>"
        f"<td>{_esc(str(item.get('goal', '')))}</td>"
        "</tr>"
        for item in proposal_items
        if isinstance(item, dict)
    )
    critique_rows = "".join(
        "<tr>"
        f"<td>{_esc(str(item.get('author_role', '')))}</td>"
        f"<td>{_esc(str(item.get('verdict', '')))}</td>"
        f"<td>{_esc('; '.join(str(note) for note in item.get('notes', [])) if isinstance(item.get('notes', []), list) else str(item.get('raw', '')))}</td>"
        "</tr>"
        for item in critique_items
        if isinstance(item, dict)
    )
    critique_table = (
        f"<h4>Pre-build critique</h4><table><thead><tr><th>Role</th><th>Verdict</th><th>Notes</th></tr></thead><tbody>{critique_rows}</tbody></table>"
        if critique_rows
        else "<p>No pre-build critique recorded.</p>"
    )
    return f"""
  <p>Selected proposal: <code>{_esc(selected_id or 'none')}</code></p>
  <table>
    <thead><tr><th>ID</th><th>Agent</th><th>Title</th><th>Supports</th><th>Goal</th></tr></thead>
    <tbody>{proposal_rows or '<tr><td colspan="5">No proposals recorded.</td></tr>'}</tbody>
  </table>
  {critique_table}
  <p><a href="./artifacts/cycle-{cycle.number:04d}-proposals.json">raw JSON</a> · <a href="./artifacts/cycle-{cycle.number:04d}-proposals.md">proposal board markdown</a></p>
"""


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
    <li><strong>sparky1</strong> — developer studio. Specialist proposers, QA Critic, Director, Designer, Builder, and Reviewer run here. Write mode applies patches on feature branches and merges on green evaluation.</li>
    <li><strong>sparky2</strong> — evaluation lab. Runs unit/build/smoke/visual gates and returns structured QA/design reports.</li>
    <li><strong>theebie.de</strong> — public runtime for the playable build, docs, and devlog.</li>
  </ul>
</section>
<section class="panel">
  <h2>Agent studio loop</h2>
  <ol>
    <li><strong>Specialist agendas</strong> live in <code>agent-agendas.json</code>. Each specialist has a mission, current goal, proposal counts, and recent feedback.</li>
    <li><strong>Proposal board</strong> artifacts (<code>cycle-####-proposals.json</code> / <code>.md</code>) collect Enemy Designer, Systems Designer, and Art Director concepts.</li>
    <li><strong>QA Critic</strong> reviews proposals before code exists, blocking vague, invisible, untestable, or trivial concepts.</li>
    <li><strong>Director</strong> selects an accepted proposal to advance; Designer and Builder receive the same board context.</li>
    <li><strong>sparky2</strong> evaluates the candidate against the selected proposal, not just the raw diff.</li>
  </ol>
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
.compact-hero { margin-bottom: 0.5rem; }
.overview-list { line-height: 1.65; margin: 0.5rem 0 0; padding-left: 1.2rem; }
.overview-sublist { margin-top: 0.35rem; }
details.fold { background: #1b1814; border: 1px solid #342e27; border-radius: 10px; margin: 0.75rem 0; }
details.fold > summary { cursor: pointer; list-style: none; display: flex; gap: 0.75rem; justify-content: space-between; align-items: baseline; padding: 0.85rem 1rem; font-weight: bold; }
details.fold > summary::-webkit-details-marker { display: none; }
.fold-title { color: #f3ead8; }
.fold-hint { color: #b7aa93; font-weight: normal; font-size: 0.92rem; text-align: right; max-width: 55ch; }
.fold-body { padding: 0 1rem 1rem; border-top: 1px solid #2a241d; }
.artifact-links { color: #c8bcaa; font-size: 0.95rem; margin: 1rem 0 2rem; }
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
