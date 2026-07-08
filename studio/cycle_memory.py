from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_backlog_summary(repo_root: Path, *, limit: int = 5) -> str:
    backlog_path = repo_root / "studio" / "backlog.jsonl"
    if not backlog_path.is_file():
        return "No backlog file yet."
    lines = [line.strip() for line in backlog_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    items: list[str] = []
    for line in lines[-limit:]:
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        title = str(entry.get("title", "")).strip()
        status = str(entry.get("status", "")).strip()
        if title:
            items.append(f"- [{status or 'backlog'}] {title}")
    return "\n".join(items) if items else "Backlog is empty."


def recent_cycle_summaries(state_dir: Path, *, before_cycle: int, limit: int = 5) -> str:
    summaries: list[str] = []
    for number in range(before_cycle - 1, max(0, before_cycle - limit - 1), -1):
        summary = _summarize_cycle(state_dir, number)
        if summary:
            summaries.append(summary)
    if not summaries:
        return "No prior studio cycles recorded yet."
    return "\n".join(reversed(summaries))


def recent_blocker_notes(state_dir: Path, *, before_cycle: int, limit: int = 3) -> str:
    notes: list[str] = []
    cycles_used = 0
    for number in range(before_cycle - 1, 0, -1):
        if cycles_used >= limit:
            break
        cycle_notes: list[str] = []
        reviewer_path = state_dir / f"cycle-{number:04d}-reviewer.json"
        if reviewer_path.is_file():
            reviewer = _read_json(reviewer_path)
            if reviewer.get("verdict") == "REWORK":
                for issue in reviewer.get("issues", []):
                    cycle_notes.append(f"Cycle {number} reviewer: {issue}")
        lint_path = state_dir / f"cycle-{number:04d}-proposal-lint.json"
        if lint_path.is_file():
            lint = _read_json(lint_path)
            if lint.get("verdict") == "REWORK":
                for issue in lint.get("issues", []):
                    cycle_notes.append(f"Cycle {number} lint: {issue}")
        report_path = state_dir / f"cycle-{number:04d}-report.json"
        if report_path.is_file():
            report = _read_json(report_path)
            for bug in report.get("qa", {}).get("bugs", []):
                cycle_notes.append(f"Cycle {number} qa: {bug}")
        if cycle_notes:
            notes.extend(cycle_notes)
            cycles_used += 1
    if not notes:
        return "No recent reviewer or lint blockers recorded."
    return "\n".join(f"- {note}" for note in notes[:12])


def append_cycle_record(
    repo_root: Path,
    *,
    cycle_number: int,
    objective: str,
    blocked: bool,
    blocking_reasons: list[str],
    mode: str,
    merge_verdict: str | None = None,
    branch: str | None = None,
) -> Path:
    history_path = repo_root / "studio" / "cycle_history.jsonl"
    history_path.parent.mkdir(parents=True, exist_ok=True)
    record: dict[str, Any] = {
        "cycle": cycle_number,
        "objective": objective,
        "mode": mode,
        "blocked": blocked,
        "blocking_reasons": blocking_reasons,
    }
    if merge_verdict:
        record["merge_verdict"] = merge_verdict
    if branch:
        record["branch"] = branch
    with history_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return history_path


def append_backlog_suggestions(repo_root: Path, suggestions: list[str], *, source_cycle: int) -> None:
    cleaned = [item.strip() for item in suggestions if item.strip()]
    if not cleaned:
        return
    backlog_path = repo_root / "studio" / "backlog.jsonl"
    backlog_path.parent.mkdir(parents=True, exist_ok=True)
    with backlog_path.open("a", encoding="utf-8") as handle:
        for index, suggestion in enumerate(cleaned):
            entry = {
                "id": f"cycle-{source_cycle:04d}-suggestion-{index + 1}",
                "priority": 3,
                "title": suggestion[:160],
                "status": "backlog",
                "notes": f"Captured from cycle {source_cycle} design report.",
            }
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _summarize_cycle(state_dir: Path, number: int) -> str | None:
    prefix = f"cycle-{number:04d}"
    director_path = state_dir / f"{prefix}-director.md"
    if not director_path.is_file():
        return None
    objective = _objective_from_director(director_path.read_text(encoding="utf-8"))
    status_parts: list[str] = []

    reviewer_path = state_dir / f"{prefix}-reviewer.json"
    if reviewer_path.is_file():
        reviewer = _read_json(reviewer_path)
        verdict = str(reviewer.get("verdict", "")).strip()
        if verdict:
            status_parts.append(f"reviewer={verdict}")

    lint_path = state_dir / f"{prefix}-proposal-lint.json"
    if lint_path.is_file():
        lint = _read_json(lint_path)
        verdict = str(lint.get("verdict", "")).strip()
        if verdict:
            status_parts.append(f"lint={verdict}")

    merge_path = state_dir / f"{prefix}-merge.json"
    if merge_path.is_file():
        merge = _read_json(merge_path)
        verdict = str(merge.get("verdict", "")).strip()
        if verdict:
            status_parts.append(f"merge={verdict}")

    report_path = state_dir / f"{prefix}-report.json"
    if report_path.is_file():
        report = _read_json(report_path)
        qa = str(report.get("qa", {}).get("verdict", "")).strip()
        design = str(report.get("design", {}).get("verdict", "")).strip()
        if qa:
            status_parts.append(f"qa={qa}")
        if design:
            status_parts.append(f"design={design}")

    status = ", ".join(status_parts) if status_parts else "incomplete"
    return f"- Cycle {number}: {objective} ({status})"


def _objective_from_director(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("objective:"):
            return stripped.split(":", 1)[1].strip()
    first = next((line.strip() for line in text.splitlines() if line.strip()), "unknown objective")
    return first


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}
