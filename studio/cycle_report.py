from __future__ import annotations

import json
import textwrap
from pathlib import Path

from studio.agent_agendas import load_agent_agendas
from studio.publish_devlog import CycleRecord

GAME_URL = "https://www.theebie.de/sites/roguelike/"
DEVLOG_URL = "https://www.theebie.de/sites/roguelike/devlog/"


def process_report_path(state_dir: Path, cycle_number: int) -> Path:
    return state_dir / f"cycle-{cycle_number:04d}-process.md"


def save_cycle_process_report(state_dir: Path, cycle_number: int) -> Path:
    path = process_report_path(state_dir, cycle_number)
    path.write_text(render_cycle_process_report(state_dir, cycle_number), encoding="utf-8")
    return path


def print_cycle_process_report(state_dir: Path, cycle_number: int) -> None:
    print(render_cycle_process_summary(state_dir, cycle_number), flush=True)


def render_cycle_process_summary(state_dir: Path, cycle_number: int) -> str:
    cycle = _load_cycle_record(state_dir, cycle_number)
    blocker = cycle.blocking_reasons[0] if cycle.blocking_reasons else ""
    merged = str(cycle.merge.get("verdict", "")).upper() == "MERGED"
    lines = [
        "",
        f"--- Cycle {cycle_number:04d} summary ---",
        f"Outcome: {'MERGED & DEPLOYED' if merged else 'BLOCKED' if cycle.blocked else 'COMPLETED'}",
        f"Concept: {_selected_label_from_cycle(cycle)}",
        f"Game: {'updated on theebie' if merged else 'unchanged (no deploy)'}",
    ]
    if blocker:
        lines.append(f"Blocked: {blocker[:160]}{'…' if len(blocker) > 160 else ''}")
    lines.extend(
        [
            f"Full story: https://www.theebie.de/sites/roguelike/devlog/cycle-{cycle_number:04d}.html",
            f"Play: https://www.theebie.de/sites/roguelike/",
            "----------------------------------------",
            "",
        ]
    )
    return "\n".join(lines)


def render_cycle_process_report(state_dir: Path, cycle_number: int) -> str:
    cycle = _load_cycle_record(state_dir, cycle_number)
    run_log = _read_run_log(state_dir, cycle_number)
    agendas = load_agent_agendas(state_dir)
    lines = [
        "═" * 72,
        f"CYCLE {cycle_number:04d} · AGENT PROCESS REPORT",
        "═" * 72,
        "",
        _outcome_section(cycle),
        "",
        "── Pipeline timeline ──",
        *(_timeline_lines(run_log) or ["(no run log)"]),
        "",
        "── Phase 1 · Specialist proposals ──",
        *_proposal_section(cycle),
        "",
        "── Phase 2 · Director selection ──",
        *_director_section(cycle),
        "",
    ]

    if cycle.designer.strip() or cycle.builder.strip() or cycle.reviewer:
        lines.extend(["── Phase 3 · Designer spec ──", *_designer_section(cycle), ""])
        lines.extend(["── Phase 4 · Builder implementation ──", *_builder_section(cycle), ""])
        lines.extend(["── Phase 5 · Reviewer gate ──", *_reviewer_section(cycle), ""])

    if cycle.report:
        lines.extend(["── Phase 6 · sparky2 evaluation ──", *_evaluation_section(cycle), ""])

    if cycle.apply or cycle.merge:
        lines.extend(["── Phase 7 · Apply, merge, deploy ──", *_write_section(cycle), ""])

    if cycle.critic:
        lines.extend(["── Cycle critic scores ──", *_critic_section(cycle), ""])

    if agendas:
        lines.extend(["── Agent agendas ──", *_agenda_section(agendas), ""])

    if cycle.blocking_reasons:
        lines.extend(["── Blocking reasons ──", *[f"- {reason}" for reason in cycle.blocking_reasons], ""])

    lines.extend(
        [
            "── Where to read more ──",
            f"- Devlog page: {DEVLOG_URL}cycle-{cycle_number:04d}.html",
            f"- Game: {GAME_URL}",
            f"- Local artifacts: studio/state/cycle-{cycle_number:04d}-*",
            "",
        ]
    )
    return "\n".join(lines)


def _selected_label_from_cycle(cycle: CycleRecord) -> str:
    proposals = cycle.proposals
    if not proposals:
        return cycle.objective or "—"
    selected_id = str(proposals.get("selected_id", "")).strip()
    items = proposals.get("proposals", [])
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict) and item.get("id") == selected_id:
                title = str(item.get("title", "")).strip()
                if title:
                    return title
    return cycle.objective or selected_id or "—"


def _load_cycle_record(state_dir: Path, cycle_number: int) -> CycleRecord:
    from studio.publish_devlog import _load_cycle

    return _load_cycle(state_dir, cycle_number)


def _outcome_section(cycle: CycleRecord) -> str:
    merged = str(cycle.merge.get("verdict", "")).upper() == "MERGED"
    if merged:
        status = "MERGED & DEPLOYED"
    elif cycle.blocked:
        status = "BLOCKED"
    else:
        status = "COMPLETED"
    lines = [
        f"Status: {status}",
        f"Objective: {cycle.objective or '(none)'}",
        f"Mode: {cycle.mode}",
        f"Branch: {cycle.branch} @ {cycle.commit}",
    ]
    if merged:
        lines.append(f"Play the change: {GAME_URL}")
    lines.append(f"Read the process: {DEVLOG_URL}cycle-{cycle.number:04d}.html")
    return "\n".join(lines)


def _timeline_lines(run_log: str) -> list[str]:
    if not run_log.strip():
        return []
    return [f"  · {line}" for line in run_log.strip().splitlines()]


def _proposal_section(cycle: CycleRecord) -> list[str]:
    proposals = cycle.proposals
    if not proposals:
        return ["No proposal board for this cycle."]
    selected_id = str(proposals.get("selected_id", "")).strip()
    items = proposals.get("proposals", [])
    critiques = proposals.get("critiques", [])
    if not isinstance(items, list):
        items = []
    if not isinstance(critiques, list):
        critiques = []

    lines: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        marker = " ★ SELECTED" if item.get("id") == selected_id else ""
        support = f" (supports {item['supports']})" if item.get("supports") else ""
        lines.append(
            f"  [{item.get('author_role', '?')}] {item.get('title', '?')}{marker}{support}"
        )
        goal = str(item.get("goal", "")).strip()
        if goal:
            lines.append(f"    Goal: {_wrap(goal, 8)}")
        acceptance = str(item.get("acceptance", "")).strip()
        if acceptance:
            lines.append(f"    Acceptance: {_wrap(acceptance, 8)}")

    for critique in critiques:
        if not isinstance(critique, dict):
            continue
        verdict = str(critique.get("verdict", "?")).upper()
        lines.append(f"  [{critique.get('author_role', 'critic')}] Verdict: {verdict}")
        notes = critique.get("notes", [])
        if isinstance(notes, list):
            for note in notes:
                lines.append(f"    - {_wrap(str(note), 6)}")

    if selected_id:
        lines.append(f"  Director will advance: {selected_id}")
    return lines


def _director_section(cycle: CycleRecord) -> list[str]:
    if not cycle.director.strip():
        return ["Director did not run (proposal-only or blocked early)."]
    return [_indent(cycle.director)]


def _designer_section(cycle: CycleRecord) -> list[str]:
    if not cycle.designer.strip():
        return ["Designer did not run."]
    return [_indent(cycle.designer)]


def _builder_section(cycle: CycleRecord) -> list[str]:
    if not cycle.builder.strip():
        return ["Builder did not run."]
    lint = cycle.proposal_lint.get("verdict")
    lines = []
    if lint:
        lines.append(f"  Proposal lint: {lint}")
    lines.append(_indent(cycle.builder))
    return lines


def _reviewer_section(cycle: CycleRecord) -> list[str]:
    verdict = str(cycle.reviewer.get("verdict", "")).strip()
    if not verdict:
        return ["Reviewer did not run."]
    lines = [f"  Verdict: {verdict}"]
    issues = cycle.reviewer.get("issues", [])
    if isinstance(issues, list):
        for issue in issues:
            lines.append(f"    - {issue}")
    return lines


def _evaluation_section(cycle: CycleRecord) -> list[str]:
    qa = cycle.report.get("qa", {})
    design = cycle.report.get("design", {})
    lines = [
        f"  QA: {qa.get('verdict', '?')}",
        f"  Design: {design.get('verdict', '?')}",
    ]
    bugs = qa.get("bugs", [])
    if isinstance(bugs, list) and bugs:
        lines.append("  QA bugs:")
        for bug in bugs:
            lines.append(f"    - {bug}")
    eval_roles = design.get("evaluation_roles", {})
    if isinstance(eval_roles, dict):
        for role, payload in eval_roles.items():
            if isinstance(payload, dict) and payload.get("verdict"):
                lines.append(f"  {role}: {payload['verdict']}")
    return lines


def _write_section(cycle: CycleRecord) -> list[str]:
    lines: list[str] = []
    if cycle.apply:
        lines.append(f"  Apply: {cycle.apply.get('verdict', '?')}")
    if cycle.merge:
        lines.append(f"  Merge: {cycle.merge.get('verdict', '?')}")
    else:
        lines.append("  Merge: not merged")
    if str(cycle.merge.get("verdict", "")).upper() == "MERGED":
        lines.append(f"  Deploy: {GAME_URL}")
    return lines


def _critic_section(cycle: CycleRecord) -> list[str]:
    scores = cycle.critic.get("scores", {})
    constraint = str(cycle.critic.get("next_cycle_constraint", "")).strip()
    lines: list[str] = []
    if isinstance(scores, dict):
        for key, value in scores.items():
            lines.append(f"  {key}: {value}")
    if constraint:
        lines.append(f"  Next cycle constraint: {constraint}")
    return lines or ["  (no critic scores)"]


def _agenda_section(agendas: dict) -> list[str]:
    lines: list[str] = []
    for role in sorted(agendas):
        agenda = agendas[role]
        lines.append(
            f"  {role}: proposed={agenda.proposed} selected={agenda.selected} "
            f"merged={agenda.merged} blocked={agenda.blocked}"
        )
        if agenda.recent_titles:
            lines.append(f"    recent: {', '.join(agenda.recent_titles[:3])}")
        if agenda.recent_feedback:
            lines.append(f"    feedback: {agenda.recent_feedback[-1]}")
    return lines


def _read_run_log(state_dir: Path, cycle_number: int) -> str:
    path = state_dir / f"cycle-{cycle_number:04d}-run.log"
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")


def _indent(text: str) -> str:
    return "\n".join(f"  {line}" for line in text.strip().splitlines())


def _wrap(text: str, indent: int) -> str:
    prefix = " " * indent
    return textwrap.fill(text, width=100, initial_indent=prefix, subsequent_indent=prefix)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Print a human-readable agent process report for one cycle.")
    parser.add_argument("--state-dir", type=Path, default=Path(__file__).resolve().parents[1] / "studio" / "state")
    parser.add_argument("--cycle", type=int, required=True)
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args(argv)

    if args.save:
        path = save_cycle_process_report(args.state_dir, args.cycle)
        print(f"saved: {path}", flush=True)
    print_cycle_process_report(args.state_dir, args.cycle)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
