from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from studio.churn_guards import (
    has_player_visible_change,
    is_src_change,
    is_test_only_change,
    requires_src_change,
)
from studio.proposals import load_proposal_board, validate_proposal_board


@dataclass(frozen=True)
class CycleCriticReport:
    scores: dict[str, int]
    next_cycle_constraint: str
    source: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "scores": dict(self.scores),
            "next_cycle_constraint": self.next_cycle_constraint,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CycleCriticReport:
        scores = data.get("scores", {})
        if not isinstance(scores, dict):
            scores = {}
        return cls(
            scores={str(key): int(value) for key, value in scores.items()},
            next_cycle_constraint=str(data.get("next_cycle_constraint", "")).strip(),
            source=str(data.get("source", "deterministic")),
        )


def critic_artifact_path(state_dir: Path, cycle_number: int) -> Path:
    return state_dir / f"cycle-{cycle_number:04d}-critic.json"


def load_latest_critic_constraint(state_dir: Path, *, before_cycle: int) -> str | None:
    for number in range(before_cycle - 1, 0, -1):
        path = critic_artifact_path(state_dir, number)
        if not path.is_file():
            continue
        try:
            report = CycleCriticReport.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            continue
        if report.next_cycle_constraint:
            return report.next_cycle_constraint
    return None


def run_cycle_critic(
    state_dir: Path,
    *,
    cycle_number: int,
    blocked: bool,
    blocking_reasons: list[str],
    merge_verdict: str | None,
    changed_files: list[str],
) -> CycleCriticReport:
    scores = _score_cycle(
        state_dir=state_dir,
        cycle_number=cycle_number,
        blocked=blocked,
        merge_verdict=merge_verdict,
        changed_files=changed_files,
        blocking_reasons=blocking_reasons,
    )
    constraint = _next_cycle_constraint(
        state_dir,
        before_cycle=cycle_number + 1,
        scores=scores,
        merge_verdict=merge_verdict,
        changed_files=changed_files,
    )
    return CycleCriticReport(scores=scores, next_cycle_constraint=constraint, source="deterministic")


def write_cycle_critic(state_dir: Path, cycle_number: int, report: CycleCriticReport) -> Path:
    path = critic_artifact_path(state_dir, cycle_number)
    path.write_text(json.dumps(report.to_dict(), indent=2) + "\n", encoding="utf-8")
    return path


def _score_cycle(
    *,
    state_dir: Path,
    cycle_number: int,
    blocked: bool,
    merge_verdict: str | None,
    changed_files: list[str],
    blocking_reasons: list[str],
) -> dict[str, int]:
    merged = merge_verdict == "MERGED"
    player_visible = 5 if has_player_visible_change(changed_files) else 1
    test_value = 5 if is_test_only_change(changed_files) else (3 if any("game/tests/" in p for p in changed_files) else 2)
    mechanical_depth = 5 if any(path.endswith("engine.ts") for path in changed_files) else 1
    scope_discipline = 5 if len(changed_files) <= 3 else 3
    if merged and is_test_only_change(changed_files):
        player_visible = 1
        mechanical_depth = 1
    if blocked:
        scope_discipline = 2 if any("gate" in reason.lower() for reason in blocking_reasons) else 3
    proposal_quality = _proposal_quality_score(state_dir, cycle_number)
    return {
        "player_visible": player_visible,
        "mechanical_depth": mechanical_depth,
        "test_value": test_value,
        "scope_discipline": scope_discipline,
        "proposal_quality": proposal_quality,
    }


def _proposal_quality_score(state_dir: Path, cycle_number: int) -> int:
    board = load_proposal_board(state_dir, cycle_number)
    if board is None:
        return 2
    issues = validate_proposal_board(board)
    if issues:
        return 1
    selected = board.selected_proposal()
    if selected is None:
        return 1
    supporting = board.supporting_proposals()
    return 5 if supporting else 4


def _next_cycle_constraint(
    state_dir: Path,
    *,
    before_cycle: int,
    scores: dict[str, int],
    merge_verdict: str | None,
    changed_files: list[str],
) -> str:
    if requires_src_change(state_dir, before_cycle=before_cycle):
        return "Mandatory: advance a specialist proposal with player-visible impact under game/src/ or game/smoke/ (not tests only)."
    if merge_verdict == "MERGED" and is_test_only_change(changed_files):
        return "Do not merge another test-only cycle; next change must touch game/src/ or game/smoke/."
    lowest_dimension = min(scores, key=scores.get)
    if lowest_dimension == "player_visible" and scores["player_visible"] <= 2:
        return "Prioritize a player-visible gameplay or HUD improvement in game/src/."
    if lowest_dimension == "mechanical_depth" and scores["mechanical_depth"] <= 2:
        return "Prioritize a mechanics change in game/src/engine.ts, not another test-only diff."
    if lowest_dimension == "proposal_quality" and scores["proposal_quality"] <= 2:
        return "Improve the specialist proposal board before implementation; require a non-trivial selected concept and critique."
    return "Prefer a small player-visible gameplay improvement over test-only churn."
