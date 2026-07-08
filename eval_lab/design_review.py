from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable

from eval_lab.protocol import DesignReport, DesignVerdict, EvaluationRequest
from studio.churn_guards import has_player_visible_change
from studio.config import StudioConfig
from studio.role_runner import run_role

RoleRunner = Callable[..., str]


def run_design_review(
    repo_root: Path,
    request: EvaluationRequest,
    *,
    roles_dir: Path,
    qa_passed: bool,
    role_runner: RoleRunner = run_role,
    role_timeout_seconds: int = 120,
) -> DesignReport:
    if not qa_passed:
        return _default_design_report(qa_passed=False)
    if request.changed_files and not has_player_visible_change(request.changed_files):
        return DesignReport(
            verdict="BLOCK",
            fun_notes=["No player-visible gameplay or HUD change detected in the candidate diff."],
            backlog_suggestions=[
                "Merge blocked: changes must touch game/src/engine.ts, game/src/main.ts, game/src/render.ts, or game/smoke/.",
                "Test-only changes are allowed during development but cannot merge until paired with a player-visible src change.",
            ],
            evaluation_roles={"player_visibility_gate": {"verdict": "BLOCK", "changed_files": list(request.changed_files)}},
        )
    if not request.models.strip():
        return _default_design_report(qa_passed=True)

    config = StudioConfig.for_evaluation(request.models)
    role_outputs: dict[str, Any] = {}
    visual_notes: list[str] = []
    fun_notes: list[str] = []
    balance_notes: list[str] = []
    backlog_suggestions: list[str] = []
    verdict: DesignVerdict = "BACKLOG"
    blocked = False

    if _should_run_role(config, "art_director"):
        try:
            raw = role_runner(
                config,
                roles_dir,
                "art_director",
                _art_director_context(repo_root, request),
                timeout_seconds=role_timeout_seconds,
            )
            parsed_verdict, notes, backlog = _parse_art_director_output(raw)
            role_outputs["art_director"] = {"verdict": parsed_verdict, "raw": raw.strip()}
            visual_notes.extend(notes)
            backlog_suggestions.extend(backlog)
            if parsed_verdict == "BLOCK":
                blocked = True
                verdict = "BLOCK"
            elif parsed_verdict == "PASS" and not blocked:
                verdict = "PASS"
        except (OSError, RuntimeError, ValueError, TimeoutError) as exc:
            role_outputs["art_director"] = {"verdict": "ERROR", "error": str(exc)}
            backlog_suggestions.append(f"Art Director role failed: {exc}")

    if _should_run_role(config, "player") and not blocked:
        try:
            raw = role_runner(
                config,
                roles_dir,
                "player",
                _player_context(request),
                timeout_seconds=role_timeout_seconds,
            )
            player_data = _parse_player_output(raw)
            role_outputs["player"] = {"raw": raw.strip(), **player_data}
            fun_notes.extend(str(note) for note in player_data.get("fun_notes", []))
            balance_notes.extend(str(note) for note in player_data.get("balance_notes", []))
            for bug in player_data.get("bugs", []):
                backlog_suggestions.append(f"Player report: {bug}")
        except (OSError, RuntimeError, ValueError, TimeoutError) as exc:
            role_outputs["player"] = {"verdict": "ERROR", "error": str(exc)}
            backlog_suggestions.append(f"Player role failed: {exc}")

    if blocked:
        verdict = "BLOCK"
    elif backlog_suggestions and verdict != "PASS":
        verdict = "BACKLOG"
    elif not role_outputs:
        return _default_design_report(qa_passed=True)

    if verdict == "PASS" and not (visual_notes or fun_notes or balance_notes):
        visual_notes.append("Evaluation roles passed with no additional notes.")

    return DesignReport(
        verdict=verdict,
        fun_notes=fun_notes,
        balance_notes=balance_notes,
        visual_notes=visual_notes or (["Automated canvas readability and screenshot baselines passed."] if qa_passed else []),
        backlog_suggestions=backlog_suggestions or _default_design_report(qa_passed=True).backlog_suggestions,
        evaluation_roles=role_outputs,
    )


def _default_design_report(*, qa_passed: bool) -> DesignReport:
    if not qa_passed:
        return DesignReport(
            verdict="BACKLOG",
            backlog_suggestions=["Address QA failures before design review."],
        )
    return DesignReport(
        verdict="BACKLOG",
        visual_notes=["Automated canvas readability and screenshot baselines passed."],
        backlog_suggestions=[
            "Add screenshot comparison and longer playthrough scenarios once visual baselines exist.",
        ],
    )


def _should_run_role(config: StudioConfig, role: str) -> bool:
    return role in config.model_assignments


def _art_director_context(repo_root: Path, request: EvaluationRequest) -> str:
    visual_style = _read_optional(repo_root / "VISUAL_STYLE.md")
    changed_lines = [f"- {path}" for path in request.changed_files] or ["- (none listed)"]
    parts = [
        f"Objective: {request.objective}",
        "",
        "Designer spec:",
        request.designer_spec.strip() or "(not provided)",
        "",
        "Candidate spec:",
        request.spec.strip(),
        "",
        "Changed files:",
        *changed_lines,
    ]
    if visual_style:
        parts.extend(["", "VISUAL_STYLE.md:", visual_style[:4000]])
    parts.extend(
        [
            "",
            "Automated npm test, build, and smoke checks passed on this candidate.",
            "Return PASS, BACKLOG: <suggestions>, or BLOCK: <blocking visual issues>.",
        ]
    )
    return "\n".join(parts)


def _player_context(request: EvaluationRequest) -> str:
    changed_lines = [f"- {path}" for path in request.changed_files] or ["- (none listed)"]
    return "\n".join(
        [
            f"Objective: {request.objective}",
            "",
            "Designer acceptance criteria:",
            request.designer_spec.strip() or "(not provided)",
            "",
            "Changed files:",
            *changed_lines,
            "",
            "You are reviewing a candidate where automated npm test/build/smoke passed.",
            "Report whether the change is player-visible (gameplay, HUD, or smoke behavior).",
            'Return JSON: { "reached": "...", "deaths": 0, "bugs": [], "fun_notes": [], "balance_notes": [] }',
        ]
    )


def _parse_art_director_output(output: str) -> tuple[DesignVerdict, list[str], list[str]]:
    stripped = output.strip()
    upper = stripped.upper()
    first_line = upper.splitlines()[0] if upper else ""
    if first_line.startswith("BLOCK"):
        detail = stripped.split(":", 1)[1].strip() if ":" in stripped.splitlines()[0] else stripped
        return "BLOCK", [], [detail or stripped]
    if first_line.startswith("BACKLOG"):
        suggestions = _bullet_lines(stripped) or [stripped]
        return "BACKLOG", [], suggestions
    if first_line.startswith("PASS"):
        notes = [line.strip() for line in stripped.splitlines()[1:] if line.strip()]
        return "PASS", notes or [stripped], []
    return "BACKLOG", [], [stripped]


def _parse_player_output(output: str) -> dict[str, Any]:
    stripped = output.strip()
    for candidate in (stripped, *_extract_json_blocks(stripped)):
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return {
                "reached": str(data.get("reached", "")),
                "deaths": int(data.get("deaths", 0)),
                "bugs": [str(item) for item in data.get("bugs", [])],
                "fun_notes": [str(item) for item in data.get("fun_notes", [])],
                "balance_notes": [str(item) for item in data.get("balance_notes", [])],
            }
    return {"fun_notes": [stripped], "bugs": [], "balance_notes": []}


def _extract_json_blocks(text: str) -> list[str]:
    blocks: list[str] = []
    for match in re.finditer(r"```(?:json)?\s*(.*?)```", text, flags=re.DOTALL | re.IGNORECASE):
        blocks.append(match.group(1).strip())
    return blocks


def _bullet_lines(text: str) -> list[str]:
    lines = []
    for line in text.splitlines():
        cleaned = re.sub(r"^[-*\d.]+\s*", "", line.strip())
        if cleaned and not cleaned.upper().startswith(("BACKLOG", "PASS", "BLOCK")):
            lines.append(cleaned)
    return lines


def _read_optional(path: Path) -> str:
    if path.is_file():
        return path.read_text(encoding="utf-8").strip()
    return ""
