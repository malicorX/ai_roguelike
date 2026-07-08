from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Callable, Sequence

from eval_lab.protocol import DesignReport, EvaluationReport, EvaluationRequest, QaReport
from studio.churn_guards import (
    changed_files_for_cycle,
    churn_director_notes,
    has_player_visible_change,
    is_test_only_designer_spec,
    is_test_only_objective,
    mandatory_gameplay_objective,
    requires_src_change,
)
from studio.config import StudioConfig, evaluation_models_string
from studio.cycle_critic import load_latest_critic_constraint, run_cycle_critic, write_cycle_critic
from studio.cycle_memory import (
    append_backlog_suggestions,
    append_cycle_record,
    load_backlog_summary,
    recent_blocker_notes,
    recent_cycle_summaries,
)
from studio.duration import parse_duration
from studio.evaluation_client import EvaluationClient, EvaluationTarget
from studio.git_ops import (
    GitOperationError,
    changed_files_against_main,
    create_cycle_branch,
    discard_branch,
    merge_branch_to_main,
    push_main,
    stage_all_and_commit,
)
from studio.patch_applier import (
    PatchApplyError,
    PatchExtractError,
    apply_unified_diff,
    extract_unified_diff,
    validate_unified_diff,
)
from studio.search_replace_applier import (
    apply_builder_patch,
    extract_builder_patch,
    validate_builder_patch,
)
from studio.write_scope import (
    allowed_builder_paths,
    primary_implementation_path,
    validate_write_scope,
)
from studio.publish_devlog import publish_site
from studio.role_runner import run_role

DEFAULT_OBJECTIVE = "Verify that the current v0 game remains playable."
DEFAULT_SPEC = "Run deterministic unit, build, and browser smoke gates before any autonomous code changes."
DEFAULT_SEEDS = [1, 7, 42]
DEFAULT_FOCUS = ["qa", "browser-smoke", "visual-readability"]
RoleRunner = Callable[..., str]


class DirectorMode(StrEnum):
    STATIC = "static"
    MODEL = "model"


@dataclass(frozen=True)
class DryCycleResult:
    request_path: Path
    report_path: Path
    blocked: bool
    blocking_reasons: list[str]


@dataclass(frozen=True)
class PilotCycleResult:
    director_path: Path
    builder_path: Path
    proposal_lint_path: Path
    request_path: Path
    report_path: Path
    blocked: bool
    blocking_reasons: list[str]
    apply_path: Path | None = None
    merge_path: Path | None = None
    branch: str | None = None


def build_evaluation_request(
    repo_root: Path,
    *,
    objective: str,
    spec: str,
    changed_files: list[str] | None = None,
    designer_spec: str = "",
    models: str = "",
) -> EvaluationRequest:
    return EvaluationRequest(
        branch=_git_output(repo_root, "rev-parse", "--abbrev-ref", "HEAD"),
        commit=_git_output(repo_root, "rev-parse", "--short", "HEAD"),
        objective=objective,
        spec=spec,
        changed_files=changed_files or [],
        seeds=list(DEFAULT_SEEDS),
        focus=list(DEFAULT_FOCUS),
        designer_spec=designer_spec,
        models=models,
    )


def run_pilot_cycle(
    repo_root: Path,
    state_dir: Path,
    *,
    objective: str = DEFAULT_OBJECTIVE,
    spec: str = DEFAULT_SPEC,
    cycle_number: int = 1,
    evaluation_target: EvaluationTarget = EvaluationTarget.LOCAL,
    director_mode: DirectorMode = DirectorMode.STATIC,
    studio_config: StudioConfig | None = None,
    roles_dir: Path | None = None,
    role_runner: RoleRunner = run_role,
    role_timeout_seconds: int = 600,
    apply_writes: bool = False,
    deploy: bool = False,
) -> PilotCycleResult:
    state_dir.mkdir(parents=True, exist_ok=True)
    studio_config = studio_config or StudioConfig()
    roles_dir = roles_dir or repo_root / "studio" / "roles"
    director_path = state_dir / f"cycle-{cycle_number:04d}-director.md"
    designer_path = state_dir / f"cycle-{cycle_number:04d}-designer.md"
    builder_path = state_dir / f"cycle-{cycle_number:04d}-builder.md"
    reviewer_path = state_dir / f"cycle-{cycle_number:04d}-reviewer.json"
    request_path = state_dir / f"cycle-{cycle_number:04d}-request.json"
    report_path = state_dir / f"cycle-{cycle_number:04d}-report.json"
    proposal_lint_path = state_dir / f"cycle-{cycle_number:04d}-proposal-lint.json"

    if report_path.is_file():
        _cycle_log(state_dir, cycle_number, "report already exists; skipping")
        return _load_pilot_cycle_result(state_dir, cycle_number)

    _cycle_log(state_dir, cycle_number, "cycle started")

    try:
        existing_director = _read_existing_artifact(director_path)
        if existing_director is not None and director_mode == DirectorMode.MODEL:
            _cycle_log(state_dir, cycle_number, "reusing director artifact")
            director_output = existing_director
        else:
            _cycle_log(state_dir, cycle_number, "running director")
            director_output = _run_director(
                repo_root,
                objective=objective,
                spec=spec,
                cycle_number=cycle_number,
                state_dir=state_dir,
                director_mode=director_mode,
                studio_config=studio_config,
                roles_dir=roles_dir,
                role_runner=role_runner,
                role_timeout_seconds=role_timeout_seconds,
                apply_writes=apply_writes,
            )
    except (TimeoutError, OSError, RuntimeError, ValueError) as exc:
        return _blocked_role_failure_result(
            repo_root,
            state_dir,
            cycle_number=cycle_number,
            objective=objective,
            spec=spec,
            role="director",
            error=str(exc),
            director_path=director_path,
            designer_path=designer_path,
            builder_path=builder_path,
            reviewer_path=reviewer_path,
            proposal_lint_path=proposal_lint_path,
            request_path=request_path,
            report_path=report_path,
            apply_writes=apply_writes,
        )

    selected_objective = _objective_from_director_output(director_output)
    if apply_writes and requires_src_change(state_dir, before_cycle=cycle_number) and is_test_only_objective(selected_objective):
        issue = f"Test-only objective rejected after recent test-only merges: {selected_objective}"
        _cycle_log(state_dir, cycle_number, "blocked at gameplay churn gate (director)")
        return _blocked_gate_result(
            repo_root,
            state_dir,
            cycle_number=cycle_number,
            objective=selected_objective,
            spec=spec,
            director_path=director_path,
            designer_path=designer_path,
            builder_path=builder_path,
            reviewer_path=reviewer_path,
            proposal_lint_path=proposal_lint_path,
            request_path=request_path,
            report_path=report_path,
            checks=["gameplay churn gate"],
            bugs=[issue],
            repro_steps=["Pick a player-visible gameplay change under game/src/ or game/smoke/."],
            blocking_reasons=["Director picked a test-only objective while gameplay churn guard is active.", issue],
        )
    if apply_writes and _is_verification_only_objective(selected_objective):
        issue = f"Verification-only objective rejected in write mode: {selected_objective}"
        _cycle_log(state_dir, cycle_number, "blocked at director objective gate")
        return _blocked_gate_result(
            repo_root,
            state_dir,
            cycle_number=cycle_number,
            objective=selected_objective,
            spec=spec,
            director_path=director_path,
            designer_path=designer_path,
            builder_path=builder_path,
            reviewer_path=reviewer_path,
            proposal_lint_path=proposal_lint_path,
            request_path=request_path,
            report_path=report_path,
            checks=["director objective gate"],
            bugs=[issue],
            repro_steps=["Pick a concrete code change in game/src, game/tests, or game/smoke."],
            blocking_reasons=["Director picked a verification-only objective in write mode.", issue],
        )
    try:
        existing_designer = _read_existing_artifact(designer_path)
        if existing_designer is not None and director_mode == DirectorMode.MODEL:
            _cycle_log(state_dir, cycle_number, "reusing designer artifact")
            designer_output = existing_designer
        else:
            _cycle_log(state_dir, cycle_number, "running designer")
            designer_output = _run_designer(
                repo_root,
                state_dir,
                cycle_number,
                selected_objective,
                director_output,
                designer_path=designer_path,
                director_mode=director_mode,
                studio_config=studio_config,
                roles_dir=roles_dir,
                role_runner=role_runner,
                role_timeout_seconds=role_timeout_seconds,
                apply_writes=apply_writes,
            )
    except (TimeoutError, OSError, RuntimeError, ValueError) as exc:
        return _blocked_role_failure_result(
            repo_root,
            state_dir,
            cycle_number=cycle_number,
            objective=selected_objective,
            spec=spec,
            role="designer",
            error=str(exc),
            director_path=director_path,
            designer_path=designer_path,
            builder_path=builder_path,
            reviewer_path=reviewer_path,
            proposal_lint_path=proposal_lint_path,
            request_path=request_path,
            report_path=report_path,
            apply_writes=apply_writes,
        )

    if apply_writes and requires_src_change(state_dir, before_cycle=cycle_number) and is_test_only_designer_spec(designer_output):
        issue = "Designer spec is test-only; gameplay churn guard requires a game/src/ or game/smoke/ change."
        _cycle_log(state_dir, cycle_number, "blocked at gameplay churn gate (designer)")
        return _blocked_gate_result(
            repo_root,
            state_dir,
            cycle_number=cycle_number,
            objective=selected_objective,
            spec=spec,
            director_path=director_path,
            designer_path=designer_path,
            builder_path=builder_path,
            reviewer_path=reviewer_path,
            proposal_lint_path=proposal_lint_path,
            request_path=request_path,
            report_path=report_path,
            checks=["gameplay churn gate"],
            bugs=[issue],
            repro_steps=["Rewrite the Designer spec to include at least one in-scope file under game/src/ or game/smoke/."],
            blocking_reasons=["Designer spec rejected by gameplay churn guard.", issue],
        )

    if apply_writes:
        write_scope_issues = validate_write_scope(designer_output)
        if write_scope_issues:
            _cycle_log(state_dir, cycle_number, f"blocked at write scope gate ({len(write_scope_issues)} issues)")
            return _blocked_gate_result(
                repo_root,
                state_dir,
                cycle_number=cycle_number,
                objective=selected_objective,
                spec=spec,
                director_path=director_path,
                designer_path=designer_path,
                builder_path=builder_path,
                reviewer_path=reviewer_path,
                proposal_lint_path=proposal_lint_path,
                request_path=request_path,
                report_path=report_path,
                checks=["write scope gate"],
                bugs=write_scope_issues,
                repro_steps=["Rewrite the Designer spec with exactly one implementation file under game/src/ or game/smoke/."],
                blocking_reasons=["Designer spec rejected by write scope guard.", *write_scope_issues],
            )

    if apply_writes and _is_verification_only_designer_spec(designer_output):
        issue = "Designer spec is verification-only and does not request a concrete code change."
        _cycle_log(state_dir, cycle_number, "blocked at designer spec gate")
        return _blocked_gate_result(
            repo_root,
            state_dir,
            cycle_number=cycle_number,
            objective=selected_objective,
            spec=spec,
            director_path=director_path,
            designer_path=designer_path,
            builder_path=builder_path,
            reviewer_path=reviewer_path,
            proposal_lint_path=proposal_lint_path,
            request_path=request_path,
            report_path=report_path,
            checks=["designer spec gate"],
            bugs=[issue],
            repro_steps=["Rewrite the Designer spec to implement the Director objective with a concrete code change."],
            blocking_reasons=["Designer spec rejected in write mode.", issue],
        )

    try:
        existing_builder = _read_existing_artifact(builder_path)
        if existing_builder is not None and director_mode == DirectorMode.MODEL:
            _cycle_log(state_dir, cycle_number, "reusing builder artifact")
            builder_output = existing_builder
        else:
            _cycle_log(state_dir, cycle_number, "running builder")
            builder_output = _run_builder(
                repo_root,
                state_dir,
                cycle_number,
                selected_objective,
                director_output,
                designer_output,
                director_mode=director_mode,
                studio_config=studio_config,
                roles_dir=roles_dir,
                role_runner=role_runner,
                role_timeout_seconds=role_timeout_seconds,
                apply_writes=apply_writes,
            )
    except (TimeoutError, OSError, RuntimeError, ValueError) as exc:
        return _blocked_role_failure_result(
            repo_root,
            state_dir,
            cycle_number=cycle_number,
            objective=selected_objective,
            spec=spec,
            role="builder",
            error=str(exc),
            director_path=director_path,
            designer_path=designer_path,
            builder_path=builder_path,
            reviewer_path=reviewer_path,
            proposal_lint_path=proposal_lint_path,
            request_path=request_path,
            report_path=report_path,
            apply_writes=apply_writes,
        )
    builder_path.write_text(builder_output.rstrip() + "\n", encoding="utf-8")

    if apply_writes:
        builder_write_issue = _builder_write_mode_issue(builder_output)
        if builder_write_issue is not None:
            _cycle_log(state_dir, cycle_number, f"blocked at builder output ({builder_write_issue})")
            return _blocked_role_failure_result(
                repo_root,
                state_dir,
                cycle_number=cycle_number,
                objective=selected_objective,
                spec=spec,
                role="builder",
                error=builder_write_issue,
                director_path=director_path,
                designer_path=designer_path,
                builder_path=builder_path,
                reviewer_path=reviewer_path,
                proposal_lint_path=proposal_lint_path,
                request_path=request_path,
                report_path=report_path,
                apply_writes=apply_writes,
            )

    pilot_spec = "\n".join(
        [
            "Phase 1 pilot: no repository writes are applied by the orchestrator yet."
            if not apply_writes
            else "Phase 1 write cycle: repository changes may be applied on a feature branch after proposal lint passes.",
            spec,
            "",
            "Designer spec:",
            designer_output.strip(),
            "",
            "Builder proposal:",
            builder_output.strip(),
        ]
    )
    proposal_issues = _lint_builder_proposal(repo_root, builder_output)
    proposal_lint_path.write_text(
        json.dumps(
            {
                "verdict": "REWORK" if proposal_issues else "PASS",
                "issues": proposal_issues,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    if proposal_issues:
        _cycle_log(state_dir, cycle_number, f"blocked at proposal lint ({len(proposal_issues)} issues)")
        return _blocked_gate_result(
            repo_root,
            state_dir,
            cycle_number=cycle_number,
            objective=selected_objective,
            spec=pilot_spec,
            director_path=director_path,
            designer_path=designer_path,
            builder_path=builder_path,
            reviewer_path=reviewer_path,
            proposal_lint_path=proposal_lint_path,
            request_path=request_path,
            report_path=report_path,
            checks=["builder proposal lint"],
            bugs=proposal_issues,
            repro_steps=["Review the Builder proposal artifact and regenerate it with real repo paths and proposal-only wording."],
            blocking_reasons=["Builder proposal lint failed.", *proposal_issues],
        )

    if apply_writes:
        patch_validation_issues: list[str] = []
        builder_allowed_paths = allowed_builder_paths(designer_output)
        for patch_attempt in range(2):
            try:
                candidate_patch = extract_builder_patch(builder_output)
                patch_validation_issues = validate_builder_patch(
                    repo_root,
                    candidate_patch,
                    allowed_paths=builder_allowed_paths,
                )
            except PatchExtractError as exc:
                patch_validation_issues = [str(exc)]
            if not patch_validation_issues:
                break
            if patch_attempt == 0 and director_mode == DirectorMode.MODEL:
                _cycle_log(
                    state_dir,
                    cycle_number,
                    f"builder patch validation failed ({len(patch_validation_issues)} issues), retrying",
                )
                try:
                    builder_output = _run_builder(
                        repo_root,
                        state_dir,
                        cycle_number,
                        selected_objective,
                        director_output,
                        designer_output,
                        director_mode=director_mode,
                        studio_config=studio_config,
                        roles_dir=roles_dir,
                        role_runner=role_runner,
                        role_timeout_seconds=role_timeout_seconds,
                        apply_writes=apply_writes,
                        patch_validation_issues=patch_validation_issues,
                    )
                except (TimeoutError, OSError, RuntimeError, ValueError) as exc:
                    return _blocked_role_failure_result(
                        repo_root,
                        state_dir,
                        cycle_number=cycle_number,
                        objective=selected_objective,
                        spec=spec,
                        role="builder",
                        error=str(exc),
                        director_path=director_path,
                        designer_path=designer_path,
                        builder_path=builder_path,
                        reviewer_path=reviewer_path,
                        proposal_lint_path=proposal_lint_path,
                        request_path=request_path,
                        report_path=report_path,
                        apply_writes=apply_writes,
                    )
                builder_path.write_text(builder_output.rstrip() + "\n", encoding="utf-8")
                continue
        if patch_validation_issues:
            _cycle_log(state_dir, cycle_number, f"blocked at patch validation ({len(patch_validation_issues)} issues)")
            return _blocked_gate_result(
                repo_root,
                state_dir,
                cycle_number=cycle_number,
                objective=selected_objective,
                spec=pilot_spec,
                director_path=director_path,
                designer_path=designer_path,
                builder_path=builder_path,
                reviewer_path=reviewer_path,
                proposal_lint_path=proposal_lint_path,
                request_path=request_path,
                report_path=report_path,
                checks=["builder patch validation"],
                bugs=patch_validation_issues,
                repro_steps=["Regenerate Builder output using search_replace blocks copied from the source excerpts."],
                blocking_reasons=["Builder patch validation failed.", *patch_validation_issues],
            )

    try:
        existing_reviewer = _read_existing_reviewer(reviewer_path)
        if existing_reviewer is not None and director_mode == DirectorMode.MODEL:
            _cycle_log(state_dir, cycle_number, f"reusing reviewer artifact ({existing_reviewer[0]})")
            reviewer_verdict, reviewer_issues = existing_reviewer
        else:
            _cycle_log(state_dir, cycle_number, "running reviewer")
            reviewer_verdict, reviewer_issues = _run_reviewer(
            repo_root,
            selected_objective,
            designer_output,
            builder_output,
            reviewer_path=reviewer_path,
            director_mode=director_mode,
            studio_config=studio_config,
            roles_dir=roles_dir,
            role_runner=role_runner,
            role_timeout_seconds=role_timeout_seconds,
            apply_writes=apply_writes,
        )
    except (TimeoutError, OSError, RuntimeError, ValueError) as exc:
        return _blocked_role_failure_result(
            repo_root,
            state_dir,
            cycle_number=cycle_number,
            objective=selected_objective,
            spec=spec,
            role="reviewer",
            error=str(exc),
            director_path=director_path,
            designer_path=designer_path,
            builder_path=builder_path,
            reviewer_path=reviewer_path,
            proposal_lint_path=proposal_lint_path,
            request_path=request_path,
            report_path=report_path,
            apply_writes=apply_writes,
        )

    if reviewer_verdict == "REWORK":
        _cycle_log(state_dir, cycle_number, "blocked at reviewer gate")
        return _blocked_gate_result(
            repo_root,
            state_dir,
            cycle_number=cycle_number,
            objective=selected_objective,
            spec=pilot_spec,
            director_path=director_path,
            designer_path=designer_path,
            builder_path=builder_path,
            reviewer_path=reviewer_path,
            proposal_lint_path=proposal_lint_path,
            request_path=request_path,
            report_path=report_path,
            checks=["reviewer gate"],
            bugs=reviewer_issues,
            repro_steps=["Revise the Builder output to address Reviewer issues, then rerun the cycle."],
            blocking_reasons=["Reviewer requested rework.", *reviewer_issues],
        )

    if apply_writes:
        _cycle_log(state_dir, cycle_number, "entering write path")
        return _run_write_cycle(
            repo_root,
            state_dir,
            cycle_number=cycle_number,
            objective=selected_objective,
            spec=spec,
            designer_output=designer_output,
            builder_output=builder_output,
            evaluation_target=evaluation_target,
            deploy=deploy,
            director_path=director_path,
            designer_path=designer_path,
            builder_path=builder_path,
            reviewer_path=reviewer_path,
            proposal_lint_path=proposal_lint_path,
            models=evaluation_models_string(studio_config),
        )

    request = build_evaluation_request(
        repo_root,
        objective=selected_objective,
        spec=pilot_spec,
        designer_spec=designer_output,
        models=evaluation_models_string(studio_config),
    )
    _cycle_log(state_dir, cycle_number, "running sparky2 evaluation")
    report = EvaluationClient(evaluation_target).evaluate(repo_root, request, state_dir, cycle_number)

    return PilotCycleResult(
        director_path=state_dir / f"cycle-{cycle_number:04d}-director.md",
        builder_path=builder_path,
        proposal_lint_path=proposal_lint_path,
        request_path=request_path,
        report_path=report_path,
        blocked=report.blocks_merge(),
        blocking_reasons=report.blocking_reasons(),
    )


def run_dry_cycle(
    repo_root: Path,
    state_dir: Path,
    *,
    objective: str = DEFAULT_OBJECTIVE,
    spec: str = DEFAULT_SPEC,
    cycle_number: int = 1,
    evaluation_target: EvaluationTarget = EvaluationTarget.LOCAL,
    director_mode: DirectorMode = DirectorMode.STATIC,
    studio_config: StudioConfig | None = None,
    roles_dir: Path | None = None,
    role_runner: RoleRunner = run_role,
    role_timeout_seconds: int = 600,
) -> DryCycleResult:
    state_dir.mkdir(parents=True, exist_ok=True)
    studio_config = studio_config or StudioConfig()
    roles_dir = roles_dir or repo_root / "studio" / "roles"
    if director_mode == DirectorMode.MODEL:
        director_output = _run_director(
            repo_root,
            objective=objective,
            spec=spec,
            cycle_number=cycle_number,
            state_dir=state_dir,
            director_mode=director_mode,
            studio_config=studio_config,
            roles_dir=roles_dir,
            role_runner=role_runner,
            role_timeout_seconds=role_timeout_seconds,
        )
        objective = _objective_from_director_output(director_output)

    request = build_evaluation_request(repo_root, objective=objective, spec=spec)
    request_path = state_dir / f"cycle-{cycle_number:04d}-request.json"
    report_path = state_dir / f"cycle-{cycle_number:04d}-report.json"
    report = EvaluationClient(evaluation_target).evaluate(repo_root, request, state_dir, cycle_number)

    return DryCycleResult(
        request_path=request_path,
        report_path=report_path,
        blocked=report.blocks_merge(),
        blocking_reasons=report.blocking_reasons(),
    )


def next_cycle_number(state_dir: Path) -> int:
    numbers: set[int] = set()
    if state_dir.is_dir():
        for path in state_dir.glob("cycle-*-director.md"):
            match = re.match(r"cycle-(\d+)-director\.md$", path.name)
            if match:
                numbers.add(int(match.group(1)))
    if not numbers:
        return 1
    latest = max(numbers)
    if not (state_dir / f"cycle-{latest:04d}-report.json").is_file():
        return latest
    return latest + 1


def _load_pilot_cycle_result(state_dir: Path, cycle_number: int) -> PilotCycleResult:
    prefix = f"cycle-{cycle_number:04d}"
    report_path = state_dir / f"{prefix}-report.json"
    report = EvaluationReport.from_dict(json.loads(report_path.read_text(encoding="utf-8")))
    apply_path = state_dir / f"{prefix}-apply.json"
    merge_path = state_dir / f"{prefix}-merge.json"
    branch: str | None = None
    if merge_path.is_file():
        branch = str(json.loads(merge_path.read_text(encoding="utf-8")).get("branch") or "") or None
    elif apply_path.is_file():
        branch = str(json.loads(apply_path.read_text(encoding="utf-8")).get("branch") or "") or None
    return PilotCycleResult(
        director_path=state_dir / f"{prefix}-director.md",
        builder_path=state_dir / f"{prefix}-builder.md",
        proposal_lint_path=state_dir / f"{prefix}-proposal-lint.json",
        request_path=state_dir / f"{prefix}-request.json",
        report_path=report_path,
        blocked=report.blocks_merge(),
        blocking_reasons=report.blocking_reasons(),
        apply_path=apply_path if apply_path.is_file() else None,
        merge_path=merge_path if merge_path.is_file() else None,
        branch=branch,
    )


def _cycle_log(state_dir: Path, cycle_number: int, message: str) -> None:
    print(f"cycle {cycle_number}: {message}", flush=True)
    log_path = state_dir / f"cycle-{cycle_number:04d}-run.log"
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(message.rstrip() + "\n")


def _read_existing_artifact(path: Path) -> str | None:
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8").strip()
    return text or None


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the ai_roguelike sparky1 studio orchestrator.")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--state-dir", type=Path, default=None)
    parser.add_argument("--time", default="30m", help="Wall-clock budget for future autonomous loops.")
    parser.add_argument("--max-cycles", type=int, default=1)
    parser.add_argument("--deploy", default="false")
    parser.add_argument("--models", default="")
    parser.add_argument("--evaluation-target", choices=[target.value for target in EvaluationTarget], default=EvaluationTarget.LOCAL.value)
    parser.add_argument("--director-mode", choices=[mode.value for mode in DirectorMode], default=DirectorMode.STATIC.value)
    parser.add_argument("--role-timeout-seconds", type=int, default=600)
    parser.add_argument("--dry-run", action="store_true", help="Run one safe local evaluation cycle.")
    parser.add_argument("--apply-writes", action="store_true", help="Apply Builder diffs on feature branches and merge on green evaluation.")
    args = parser.parse_args(argv)

    studio_config = StudioConfig.from_model_string(args.models)
    state_dir = args.state_dir or args.repo_root / "studio" / "state"
    evaluation_target = EvaluationTarget(args.evaluation_target)
    director_mode = DirectorMode(args.director_mode)

    cycles = max(1, args.max_cycles)
    start_cycle = next_cycle_number(state_dir)
    deadline = time.monotonic() + parse_duration(args.time)
    print(
        f"orchestrator starting: cycles={cycles} from={start_cycle} time_budget={args.time} apply_writes={args.apply_writes}",
        flush=True,
    )
    last_blocked = False
    completed = 0
    while completed < cycles:
        if time.monotonic() >= deadline:
            print(f"time budget {args.time} elapsed; exiting before next cycle.", flush=True)
            break
        cycle_number = next_cycle_number(state_dir)
        if (state_dir / "STOP").exists():
            print(f"STOP file found at {state_dir / 'STOP'}; exiting before cycle {cycle_number}.", flush=True)
            break
        if args.dry_run:
            dry_result = run_dry_cycle(
                args.repo_root,
                state_dir,
                cycle_number=cycle_number,
                evaluation_target=evaluation_target,
                director_mode=director_mode,
                studio_config=studio_config,
                role_timeout_seconds=args.role_timeout_seconds,
            )
            last_blocked = dry_result.blocked
            print(f"cycle {cycle_number}: report={dry_result.report_path} blocked={dry_result.blocked}", flush=True)
            _publish_devlog(args.repo_root, state_dir)
            completed += 1
            continue

        pilot_result = run_pilot_cycle(
            args.repo_root,
            state_dir,
            cycle_number=cycle_number,
            evaluation_target=evaluation_target,
            director_mode=director_mode,
            studio_config=studio_config,
            role_timeout_seconds=args.role_timeout_seconds,
            apply_writes=args.apply_writes,
            deploy=_deploy_enabled(args.deploy),
        )
        last_blocked = pilot_result.blocked
        print(
            f"cycle {cycle_number}: director={pilot_result.director_path} "
            f"builder={pilot_result.builder_path} report={pilot_result.report_path} "
            f"branch={pilot_result.branch} blocked={pilot_result.blocked}",
            flush=True,
        )
        _publish_devlog(args.repo_root, state_dir)
        _finalize_cycle(args.repo_root, state_dir, cycle_number, pilot_result, apply_writes=args.apply_writes)
        completed += 1

    return 1 if last_blocked else 0


def _finalize_cycle(
    repo_root: Path,
    state_dir: Path,
    cycle_number: int,
    result: PilotCycleResult,
    *,
    apply_writes: bool,
) -> None:
    objective = _objective_from_director_output(result.director_path.read_text(encoding="utf-8"))
    merge_verdict: str | None = None
    merge_path = state_dir / f"cycle-{cycle_number:04d}-merge.json"
    if merge_path.is_file():
        merge_data = json.loads(merge_path.read_text(encoding="utf-8"))
        merge_verdict = str(merge_data.get("verdict", "")).strip() or None
    branch = result.branch if isinstance(result.branch, (str, type(None))) else None
    changed_files = changed_files_for_cycle(state_dir, cycle_number)
    critic_report = run_cycle_critic(
        state_dir,
        cycle_number=cycle_number,
        blocked=result.blocked,
        blocking_reasons=result.blocking_reasons,
        merge_verdict=merge_verdict,
        changed_files=changed_files,
    )
    write_cycle_critic(state_dir, cycle_number, critic_report)
    append_cycle_record(
        repo_root,
        cycle_number=cycle_number,
        objective=objective,
        blocked=result.blocked,
        blocking_reasons=result.blocking_reasons,
        mode="write" if apply_writes else "proposal",
        merge_verdict=merge_verdict,
        branch=branch,
    )
    if result.blocked or merge_verdict != "MERGED":
        return
    if not result.report_path.is_file():
        return
    try:
        report_data = json.loads(result.report_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return
    suggestions = report_data.get("design", {}).get("backlog_suggestions", [])
    if isinstance(suggestions, list):
        append_backlog_suggestions(repo_root, [str(item) for item in suggestions], source_cycle=cycle_number)


def _publish_devlog(repo_root: Path, state_dir: Path) -> None:
    out_dir = repo_root / "site"
    result = publish_site(repo_root, state_dir, out_dir)
    print(f"published devlog: {result.devlog_index} ({result.cycle_count} cycles)", flush=True)
    _sync_public_devlog(repo_root)


def _sync_public_devlog(repo_root: Path) -> None:
    script = repo_root / "deploy" / "sync_devlog.sh"
    if not script.is_file():
        return
    sync = subprocess.run(["bash", str(script)], cwd=repo_root, capture_output=True, text=True, check=False)
    if sync.returncode != 0:
        print(f"devlog sync failed: {sync.stderr.strip() or sync.stdout.strip()}", flush=True)
    elif sync.stdout.strip():
        print(sync.stdout.strip(), flush=True)


def _deploy_enabled(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "theebie"}


def _run_deploy(repo_root: Path) -> None:
    script = repo_root / "deploy" / "deploy_static.sh"
    subprocess.run(["bash", str(script)], cwd=repo_root, check=True)


def _run_write_cycle(
    repo_root: Path,
    state_dir: Path,
    *,
    cycle_number: int,
    objective: str,
    spec: str,
    designer_output: str,
    builder_output: str,
    evaluation_target: EvaluationTarget,
    deploy: bool,
    director_path: Path,
    designer_path: Path,
    builder_path: Path,
    reviewer_path: Path,
    proposal_lint_path: Path,
    models: str = "",
) -> PilotCycleResult:
    request_path = state_dir / f"cycle-{cycle_number:04d}-request.json"
    report_path = state_dir / f"cycle-{cycle_number:04d}-report.json"
    apply_path = state_dir / f"cycle-{cycle_number:04d}-apply.json"
    merge_path = state_dir / f"cycle-{cycle_number:04d}-merge.json"
    branch: str | None = None

    try:
        patch = extract_builder_patch(builder_output)
    except PatchExtractError as exc:
        return _blocked_write_result(
            repo_root,
            state_dir,
            cycle_number=cycle_number,
            objective=objective,
            spec=spec,
            builder_output=builder_output,
            director_path=director_path,
            builder_path=builder_path,
            proposal_lint_path=proposal_lint_path,
            request_path=request_path,
            report_path=report_path,
            reasons=[str(exc)],
            checks=["builder patch extraction"],
        )

    patch_validation_issues = validate_builder_patch(repo_root, patch)
    if patch_validation_issues:
        return _blocked_write_result(
            repo_root,
            state_dir,
            cycle_number=cycle_number,
            objective=objective,
            spec=spec,
            builder_output=builder_output,
            director_path=director_path,
            builder_path=builder_path,
            proposal_lint_path=proposal_lint_path,
            request_path=request_path,
            report_path=report_path,
            reasons=patch_validation_issues,
            checks=["builder patch validation"],
        )

    try:
        branch = create_cycle_branch(repo_root, cycle_number, objective)
        apply_builder_patch(repo_root, patch)
        commit = stage_all_and_commit(repo_root, f"cycle {cycle_number}: {objective}")
        changed_files = changed_files_against_main(repo_root)
        apply_path.write_text(
            json.dumps(
                {
                    "branch": branch,
                    "commit": commit,
                    "changed_files": changed_files,
                    "verdict": "APPLIED",
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    except (PatchApplyError, GitOperationError) as exc:
        if branch is not None:
            discard_branch(repo_root, branch)
        return _blocked_write_result(
            repo_root,
            state_dir,
            cycle_number=cycle_number,
            objective=objective,
            spec=spec,
            builder_output=builder_output,
            director_path=director_path,
            builder_path=builder_path,
            proposal_lint_path=proposal_lint_path,
            request_path=request_path,
            report_path=report_path,
            reasons=[str(exc)],
            checks=["builder diff apply"],
        )

    local_build_issues = _run_local_game_build_gate(repo_root)
    if local_build_issues:
        if branch is not None:
            discard_branch(repo_root, branch)
        return _blocked_write_result(
            repo_root,
            state_dir,
            cycle_number=cycle_number,
            objective=objective,
            spec=spec,
            builder_output=builder_output,
            director_path=director_path,
            builder_path=builder_path,
            proposal_lint_path=proposal_lint_path,
            request_path=request_path,
            report_path=report_path,
            reasons=local_build_issues,
            checks=["local npm run build"],
        )

    write_spec = "\n".join(
        [
            "Phase 1 write cycle: repository changes were applied on a feature branch before evaluation.",
            spec,
            "",
            "Designer spec:",
            designer_output.strip(),
            "",
            "Builder proposal:",
            builder_output.strip(),
        ]
    )
    request = EvaluationRequest(
        branch=branch or "unknown",
        commit=commit,
        objective=objective,
        spec=write_spec,
        changed_files=changed_files,
        seeds=list(DEFAULT_SEEDS),
        focus=list(DEFAULT_FOCUS),
        designer_spec=designer_output,
        models=models,
    )
    report = EvaluationClient(evaluation_target).evaluate(repo_root, request, state_dir, cycle_number)

    if not has_player_visible_change(changed_files):
        if branch is not None:
            discard_branch(repo_root, branch)
        return PilotCycleResult(
            director_path=director_path,
            builder_path=builder_path,
            proposal_lint_path=proposal_lint_path,
            request_path=request_path,
            report_path=report_path,
            blocked=True,
            blocking_reasons=[
                "Player visibility gate blocked merge.",
                "Changes must touch game/src/engine.ts, game/src/main.ts, game/src/render.ts, or game/smoke/.",
            ],
            apply_path=apply_path,
            branch=branch,
        )

    if report.blocks_merge():
        if branch is not None:
            discard_branch(repo_root, branch)
        return PilotCycleResult(
            director_path=director_path,
            builder_path=builder_path,
            proposal_lint_path=proposal_lint_path,
            request_path=request_path,
            report_path=report_path,
            blocked=True,
            blocking_reasons=report.blocking_reasons(),
            apply_path=apply_path,
            branch=branch,
        )

    merge_branch_to_main(repo_root, branch or "unknown", message=f"Merge {branch}")
    merge_path.write_text(
        json.dumps(
            {
                "branch": branch,
                "commit": commit,
                "verdict": "MERGED",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    push_main(repo_root)
    if deploy:
        _run_deploy(repo_root)

    return PilotCycleResult(
        director_path=director_path,
        builder_path=builder_path,
        proposal_lint_path=proposal_lint_path,
        request_path=request_path,
        report_path=report_path,
        blocked=False,
        blocking_reasons=[],
        apply_path=apply_path,
        merge_path=merge_path,
        branch=branch,
    )


def _blocked_gate_result(
    repo_root: Path,
    state_dir: Path,
    *,
    cycle_number: int,
    objective: str,
    spec: str,
    director_path: Path,
    designer_path: Path,
    builder_path: Path,
    reviewer_path: Path,
    proposal_lint_path: Path,
    request_path: Path,
    report_path: Path,
    checks: list[str],
    bugs: list[str],
    repro_steps: list[str],
    blocking_reasons: list[str],
) -> PilotCycleResult:
    request = build_evaluation_request(repo_root, objective=objective, spec=spec)
    request_path.write_text(json.dumps(request.to_dict(), indent=2) + "\n", encoding="utf-8")
    report = EvaluationReport(
        request_branch=request.branch,
        request_commit=request.commit,
        qa=QaReport(
            verdict="REWORK",
            checks=checks,
            bugs=bugs,
            repro_steps=repro_steps,
        ),
        design=DesignReport(
            verdict="BACKLOG",
            backlog_suggestions=["Address sparky1 gate failures before sparky2 evaluation."],
        ),
    )
    report_path.write_text(json.dumps(report.to_dict(), indent=2) + "\n", encoding="utf-8")
    return PilotCycleResult(
        director_path=director_path,
        builder_path=builder_path,
        proposal_lint_path=proposal_lint_path,
        request_path=request_path,
        report_path=report_path,
        blocked=True,
        blocking_reasons=blocking_reasons,
    )


def _blocked_write_result(
    repo_root: Path,
    state_dir: Path,
    *,
    cycle_number: int,
    objective: str,
    spec: str,
    builder_output: str,
    director_path: Path,
    builder_path: Path,
    proposal_lint_path: Path,
    request_path: Path,
    report_path: Path,
    reasons: list[str],
    checks: list[str],
) -> PilotCycleResult:
    write_spec = "\n".join(
        [
            "Phase 1 write cycle: repository writes were attempted but blocked before merge.",
            spec,
            "",
            "Builder proposal:",
            builder_output.strip(),
        ]
    )
    request = build_evaluation_request(repo_root, objective=objective, spec=write_spec)
    request_path.write_text(json.dumps(request.to_dict(), indent=2) + "\n", encoding="utf-8")
    report = EvaluationReport(
        request_branch=request.branch,
        request_commit=request.commit,
        qa=QaReport(
            verdict="REWORK",
            checks=checks,
            bugs=reasons,
            repro_steps=["Review the Builder diff artifact and regenerate a clean unified diff."],
        ),
        design=DesignReport(
            verdict="BACKLOG",
            backlog_suggestions=["Keep write-cycle diffs small and limited to the selected objective."],
        ),
    )
    report_path.write_text(json.dumps(report.to_dict(), indent=2) + "\n", encoding="utf-8")
    return PilotCycleResult(
        director_path=director_path,
        builder_path=builder_path,
        proposal_lint_path=proposal_lint_path,
        request_path=request_path,
        report_path=report_path,
        blocked=True,
        blocking_reasons=["Write cycle blocked before evaluation.", *reasons],
    )


def _blocked_role_failure_result(
    repo_root: Path,
    state_dir: Path,
    *,
    cycle_number: int,
    objective: str,
    spec: str,
    role: str,
    error: str,
    director_path: Path,
    designer_path: Path,
    builder_path: Path,
    reviewer_path: Path,
    proposal_lint_path: Path,
    request_path: Path,
    report_path: Path,
    apply_writes: bool,
) -> PilotCycleResult:
    if not builder_path.is_file():
        builder_path.write_text(f"{role.title()} role failed before Builder output.\n", encoding="utf-8")
    if not designer_path.is_file() and role in {"builder", "reviewer"}:
        designer_path.write_text(f"{role.title()} role failed before Designer output.\n", encoding="utf-8")
    if not reviewer_path.is_file() and role == "reviewer":
        reviewer_path.write_text(json.dumps({"verdict": "REWORK", "issues": [error]}, indent=2) + "\n", encoding="utf-8")
    proposal_lint_path.write_text(
        json.dumps({"verdict": "REWORK", "issues": [f"{role} role failed: {error}"]}, indent=2) + "\n",
        encoding="utf-8",
    )
    mode_line = (
        "Phase 1 write cycle: repository writes were not attempted because a studio role failed."
        if apply_writes
        else "Phase 1 pilot: repository writes are disabled and a studio role failed."
    )
    request = build_evaluation_request(
        repo_root,
        objective=objective,
        spec="\n".join([mode_line, spec]),
    )
    request_path.write_text(json.dumps(request.to_dict(), indent=2) + "\n", encoding="utf-8")
    report = EvaluationReport(
        request_branch=request.branch,
        request_commit=request.commit,
        qa=QaReport(
            verdict="REWORK",
            checks=[f"{role} role"],
            bugs=[error],
            repro_steps=[f"Retry the cycle after the {role} model endpoint responds within the role timeout."],
        ),
        design=DesignReport(
            verdict="BACKLOG",
            backlog_suggestions=["Keep studio role calls within the configured timeout or increase --role-timeout-seconds."],
        ),
    )
    report_path.write_text(json.dumps(report.to_dict(), indent=2) + "\n", encoding="utf-8")
    return PilotCycleResult(
        director_path=director_path,
        builder_path=builder_path,
        proposal_lint_path=proposal_lint_path,
        request_path=request_path,
        report_path=report_path,
        blocked=True,
        blocking_reasons=[f"{role.title()} role failed.", error],
    )


def _git_output(repo_root: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", *args],
        cwd=repo_root,
        text=True,
        stderr=subprocess.DEVNULL,
    ).strip()


def _director_context(
    repo_root: Path,
    state_dir: Path,
    cycle_number: int,
    *,
    objective: str,
    spec: str,
    apply_writes: bool,
) -> str:
    branch = _git_output(repo_root, "rev-parse", "--abbrev-ref", "HEAD")
    commit = _git_output(repo_root, "rev-parse", "--short", "HEAD")
    mode_line = (
        "Phase 1 write cycle: Builder diffs apply on feature branches and merge on green sparky2 evaluation."
        if apply_writes
        else "Phase 1 pilot: proposal only — no repository writes are applied."
    )
    write_rules = (
        [
            "",
            "Write-mode rules:",
            "- Objectives must request concrete, small game changes (game/src, game/tests, game/smoke).",
            "- Pick one implementation file per cycle (game/src/ or game/smoke/); defer test edits to later cycles.",
            "- After diff/patch validation failures, pick a smaller single-file change with obvious anchor code.",
            "- Do not pick verification-only objectives that forbid code changes.",
            "- After a test-only merge, the next cycle must include a player-visible game/src/ or game/smoke/ change.",
            "- Avoid repeating objectives that recently blocked at reviewer or lint.",
        ]
        if apply_writes
        else []
    )
    return "\n".join(
        [
            f"Branch: {branch}",
            f"Commit: {commit}",
            f"Cycle number: {cycle_number}",
            f"Mode: {mode_line}",
            *write_rules,
            "",
            "Backlog (latest items):",
            load_backlog_summary(repo_root),
            "",
            "Recent cycle outcomes (avoid repeating blocked objectives):",
            recent_cycle_summaries(state_dir, before_cycle=cycle_number),
            "",
            "Recent blockers (do not repeat these failure patterns):",
            recent_blocker_notes(state_dir, before_cycle=cycle_number),
            *(
                [""] + churn_director_notes(state_dir, before_cycle=cycle_number)
                if churn_director_notes(state_dir, before_cycle=cycle_number)
                else []
            ),
            *(
                [
                    "",
                    "Cycle critic constraint for this cycle:",
                    constraint,
                ]
                if (constraint := load_latest_critic_constraint(state_dir, before_cycle=cycle_number))
                else []
            ),
            *(
                [
                    "",
                    "Mandatory gameplay objective (use unless you have a better player-visible idea):",
                    mandatory,
                ]
                if (mandatory := mandatory_gameplay_objective(state_dir, before_cycle=cycle_number))
                else []
            ),
            *(
                [
                    "",
                    "Suggested objective after repeated diff failures:",
                    suggestion,
                ]
                if (suggestion := _suggested_write_objective(state_dir, before_cycle=cycle_number))
                else []
            ),
            "",
            f"Fallback objective if unsure: {objective}",
            f"Fallback spec if unsure: {spec}",
            "",
            "Pick the next small player-visible gameplay or HUD improvement (not test-only churn).",
        ]
    )


def _run_director(
    repo_root: Path,
    *,
    objective: str,
    spec: str,
    cycle_number: int,
    state_dir: Path,
    director_mode: DirectorMode,
    studio_config: StudioConfig,
    roles_dir: Path,
    role_runner: RoleRunner,
    role_timeout_seconds: int,
    apply_writes: bool = False,
) -> str:
    if director_mode == DirectorMode.STATIC:
        director_output = f"Objective: {objective}\nReason: {spec}"
    else:
        director_output = role_runner(
            studio_config,
            roles_dir,
            "director",
            _director_context(
                repo_root,
                state_dir,
                cycle_number,
                objective=objective,
                spec=spec,
                apply_writes=apply_writes,
            ),
            timeout_seconds=role_timeout_seconds,
        )
    (state_dir / f"cycle-{cycle_number:04d}-director.md").write_text(director_output.rstrip() + "\n", encoding="utf-8")
    return director_output


def _designer_context(
    repo_root: Path,
    state_dir: Path,
    cycle_number: int,
    objective: str,
    director_output: str,
    *,
    apply_writes: bool = False,
) -> str:
    file_summary = "\n".join(f"- {path}" for path in _known_repo_files(repo_root))
    command_summary = "\n".join(f"- {command}" for command in _known_test_commands(repo_root))
    write_scope_rules = (
        [
            "",
            "Write-mode scope rules:",
            "- List exactly ONE implementation file under game/src/ or game/smoke/ in In-scope files.",
            "- Put game/tests/ updates in Out of scope; sparky2 will report regressions after src applies.",
            "- Prefer editing existing functions over creating new modules.",
        ]
        if apply_writes
        else []
    )
    return "\n".join(
        [
            f"Objective: {objective}",
            "",
            "Director output:",
            director_output.strip(),
            "",
            "Recent blockers to avoid:",
            recent_blocker_notes(state_dir, before_cycle=cycle_number),
            "",
            "Write a Designer spec only. No code, no diffs.",
            "Canvas HUD/overlay text uses ctx.fillText — do not specify toGlyphGrid() string checks for overlay text.",
            "",
            "GameState fields (use these exact names in specs): seed, turn, map, player, enemies, log, diagnostics.",
            "",
            "Gameplay churn guard: if recent merges were test-only, in-scope files must include game/src/ or game/smoke/.",
            *write_scope_rules,
            "",
            "Known existing paths:",
            file_summary,
            "",
            "Known test commands:",
            command_summary,
        ]
    )


def _run_designer(
    repo_root: Path,
    state_dir: Path,
    cycle_number: int,
    objective: str,
    director_output: str,
    *,
    designer_path: Path,
    director_mode: DirectorMode,
    studio_config: StudioConfig,
    roles_dir: Path,
    role_runner: RoleRunner,
    role_timeout_seconds: int,
    apply_writes: bool = False,
) -> str:
    if director_mode == DirectorMode.STATIC:
        designer_output = "\n".join(
            [
                "## Summary",
                f"Implement the objective: {objective}",
                "",
                "## Acceptance criteria",
                "1. Existing npm test, build, and smoke gates remain green.",
                "2. Change is visible in gameplay or covered by a new unit test.",
                "",
                "## In-scope files",
                "- `game/src/main.ts`",
                "",
                "## Out of scope",
                "- Studio tooling and refactors unrelated to the objective.",
                "- `game/tests/` updates in this cycle.",
                "",
                "## Test plan",
                "- npm test",
                "- npm run build",
                "- npm run smoke",
            ]
        )
    else:
        designer_output = role_runner(
            studio_config,
            roles_dir,
            "designer",
            _designer_context(
                repo_root,
                state_dir,
                cycle_number,
                objective,
                director_output,
                apply_writes=apply_writes,
            ),
            timeout_seconds=role_timeout_seconds,
        )
    designer_path.write_text(designer_output.rstrip() + "\n", encoding="utf-8")
    return designer_output


def _builder_context(
    repo_root: Path,
    state_dir: Path,
    cycle_number: int,
    objective: str,
    director_output: str,
    designer_output: str,
    *,
    apply_writes: bool = False,
) -> str:
    file_summary = "\n".join(f"- {path}" for path in _builder_repo_files(repo_root, designer_output))
    command_summary = "\n".join(f"- {command}" for command in _known_test_commands(repo_root))
    mode_line = (
        "Mode: Phase 1 write cycle. Return an implementation summary and one or more ```search_replace blocks."
        if apply_writes
        else "Mode: Phase 1 pilot. Return an implementation proposal only; do not claim files were changed."
    )
    if apply_writes:
        extra_rules = (
            "Prefer ```search_replace path blocks with <<<<<<< SEARCH / ======= / >>>>>>> REPLACE sections copied "
            "exactly from the source excerpts below. Use ```new_file path only for brand-new files. "
            "Unified ```diff is a last resort for simple single-hunk edits. "
            "REQUIRED: include at least one applicable search_replace, new_file, or diff block. Empty responses are rejected."
        )
    else:
        extra_rules = "Do not claim tests were run. You may recommend test commands to run later."
    parts = [
        f"Selected objective: {objective}",
        "",
        "Director output:",
        director_output.strip(),
        "",
        "Designer spec (implement this only):",
        designer_output.strip(),
        "",
        "Recent blockers to avoid:",
        recent_blocker_notes(state_dir, before_cycle=cycle_number),
        "",
        mode_line,
        "Do not invent paths. Proposed changed files must match the Designer spec or be labeled as NEW.",
        extra_rules,
        "",
        "Known existing paths:",
        file_summary,
        "",
        "Known test commands:",
        command_summary,
    ]
    if apply_writes:
        primary = primary_implementation_path(designer_output)
        allowed = allowed_builder_paths(designer_output)
        if primary:
            parts.extend(["", f"Primary file (edit ONLY this path unless adding a NEW file): `{primary}`"])
        snippet_paths = [primary] if primary else _builder_repo_files(repo_root, designer_output)[:8]
        snippets = _source_snippets(repo_root, snippet_paths, scoped_paths=allowed or set(_paths_from_designer_spec(designer_output)))
        if snippets:
            parts.extend(
                [
                    "",
                    "Current source excerpts (SEARCH blocks must copy text exactly from here):",
                    snippets,
                ]
            )
    return "\n".join(parts)


def _reviewer_context(
    repo_root: Path,
    objective: str,
    designer_output: str,
    builder_output: str,
    *,
    apply_writes: bool = False,
) -> str:
    parts = [
        f"Objective: {objective}",
        "",
        "Designer spec:",
        designer_output.strip(),
        "",
        "Builder output to review:",
        builder_output.strip(),
    ]
    if apply_writes:
        snippet_paths = _builder_repo_files(repo_root, designer_output)[:8]
        scoped_paths = set(_paths_from_designer_spec(designer_output))
        snippets = _source_snippets(repo_root, snippet_paths, scoped_paths=scoped_paths)
        if snippets:
            parts.extend(
                [
                    "",
                    "Current source excerpts (reject diffs whose removed/context lines are not present here):",
                    snippets,
                ]
            )
    return "\n".join(parts)


def _run_reviewer(
    repo_root: Path,
    objective: str,
    designer_output: str,
    builder_output: str,
    *,
    reviewer_path: Path,
    director_mode: DirectorMode,
    studio_config: StudioConfig,
    roles_dir: Path,
    role_runner: RoleRunner,
    role_timeout_seconds: int,
    apply_writes: bool = False,
) -> tuple[str, list[str]]:
    if director_mode == DirectorMode.STATIC:
        reviewer_output = "PASS"
    else:
        reviewer_output = role_runner(
            studio_config,
            roles_dir,
            "reviewer",
            _reviewer_context(
                repo_root,
                objective,
                designer_output,
                builder_output,
                apply_writes=apply_writes,
            ),
            timeout_seconds=role_timeout_seconds,
        )
    verdict, issues = _parse_reviewer_verdict(reviewer_output)
    reviewer_path.write_text(
        json.dumps({"verdict": verdict, "issues": issues, "raw": reviewer_output.strip()}, indent=2) + "\n",
        encoding="utf-8",
    )
    return verdict, issues


def _parse_reviewer_verdict(output: str) -> tuple[str, list[str]]:
    stripped = output.strip()
    upper = stripped.upper()
    if upper.startswith("PASS") and "REWORK" not in upper.splitlines()[0]:
        return "PASS", []
    issues: list[str] = []
    for line in stripped.splitlines():
        if re.match(r"^\d+\.\s+", line.strip()):
            issues.append(line.strip())
    if "REWORK" in upper:
        if not issues:
            issues = [line.strip() for line in stripped.splitlines() if line.strip() and not line.strip().upper().startswith("REWORK")]
        return "REWORK", issues or [stripped]
    return "REWORK", [f"Reviewer output must start with PASS or REWORK: {stripped[:240]}"]


def _source_snippets(
    repo_root: Path,
    paths: list[str],
    *,
    max_lines: int = 50,
    scoped_paths: set[str] | None = None,
    scoped_full_file_max_lines: int = 250,
    scoped_partial_head_lines: int = 80,
    scoped_partial_tail_lines: int = 80,
) -> str:
    blocks: list[str] = []
    for path in paths:
        source = repo_root / path
        if not source.is_file():
            continue
        lines = source.read_text(encoding="utf-8").splitlines()
        if scoped_paths and path in scoped_paths:
            if len(lines) <= scoped_full_file_max_lines:
                excerpt_lines = lines
            elif len(lines) <= scoped_partial_head_lines + scoped_partial_tail_lines:
                excerpt_lines = lines
            else:
                omitted = len(lines) - scoped_partial_head_lines - scoped_partial_tail_lines
                excerpt_lines = [
                    *lines[:scoped_partial_head_lines],
                    f"// ... {omitted} lines omitted; copy context only from lines shown below ...",
                    *lines[-scoped_partial_tail_lines:],
                ]
        else:
            excerpt_lines = lines[: min(len(lines), max_lines)]
        numbered = "\n".join(f"{index + 1:4d}| {line}" for index, line in enumerate(excerpt_lines))
        blocks.append(
            f"#### {path}\n```typescript\n{numbered}\n```\n"
            "(Copy diff context from these lines exactly; omit the `NNNN| ` line-number prefixes.)"
        )
    return "\n\n".join(blocks)


def _run_builder(
    repo_root: Path,
    state_dir: Path,
    cycle_number: int,
    objective: str,
    director_output: str,
    designer_output: str,
    *,
    director_mode: DirectorMode,
    studio_config: StudioConfig,
    roles_dir: Path,
    role_runner: RoleRunner,
    role_timeout_seconds: int,
    apply_writes: bool = False,
    patch_validation_issues: list[str] | None = None,
) -> str:
    if director_mode == DirectorMode.STATIC:
        return "\n".join(
            [
                "Implementation summary: no-write static pilot proposal.",
                "Changed files: none.",
                "Tests: delegated to evaluation client.",
                f"Objective considered: {objective}",
            ]
        )
    context = _builder_context(
        repo_root,
        state_dir,
        cycle_number,
        objective,
        director_output,
        designer_output,
        apply_writes=apply_writes,
    )
    if patch_validation_issues:
        context = "\n".join(
            [
                context,
                "",
                "Your previous patch was rejected by patch validation:",
                *[f"- {issue}" for issue in patch_validation_issues],
                "",
                "Regenerate using ```search_replace blocks with SEARCH text copied exactly from the excerpts above. "
                "Make the smallest possible edit to the primary file only.",
            ]
        )
    output = role_runner(
        studio_config,
        roles_dir,
        "builder",
        context,
        timeout_seconds=role_timeout_seconds,
    )
    if apply_writes and _builder_write_mode_issue(output) is not None:
        output = role_runner(
            studio_config,
            roles_dir,
            "builder",
            context
            + "\n\nYour previous response was rejected because write mode requires search_replace, new_file, or diff blocks. Try again.",
            timeout_seconds=role_timeout_seconds,
        )
    return output


def _builder_write_mode_issue(builder_output: str) -> str | None:
    if not builder_output.strip():
        return "Builder returned empty output in write mode."
    try:
        patch = extract_builder_patch(builder_output)
    except PatchExtractError as exc:
        return str(exc)
    if not patch.has_edits():
        return "Builder output did not include search_replace, new_file, or unified diff blocks."
    return None


def _builder_repo_files(repo_root: Path, designer_output: str) -> list[str]:
    scoped = _paths_from_designer_spec(designer_output)
    defaults = [
        "game/src/engine.ts",
        "game/src/main.ts",
        "game/src/render.ts",
        "game/src/testHarness.ts",
        "game/tests/engine.test.ts",
        "game/smoke/playability.spec.ts",
    ]
    paths: list[str] = []
    seen: set[str] = set()
    for candidate in [*scoped, *defaults, *_known_repo_files(repo_root, scope="game")]:
        if candidate in seen:
            continue
        if (repo_root / candidate).is_file():
            seen.add(candidate)
            paths.append(candidate)
        if len(paths) >= 24:
            break
    return paths


def _paths_from_designer_spec(designer_output: str) -> list[str]:
    paths: list[str] = []
    for match in re.findall(r"`([^`]+)`", designer_output):
        cleaned = match.strip().removeprefix("NEW:").strip()
        if cleaned.endswith("/"):
            continue
        if _looks_like_repo_path(cleaned):
            paths.append(cleaned)
    return paths


def _known_repo_files(repo_root: Path, *, scope: str = "all") -> list[str]:
    if scope == "game":
        patterns = [
            "game/src/**/*.ts",
            "game/tests/**/*.ts",
            "game/smoke/**/*.ts",
        ]
    else:
        patterns = [
            "game/src/**/*.ts",
            "game/tests/**/*.ts",
            "game/smoke/**/*.ts",
            "eval_lab/**/*.py",
            "studio/**/*.py",
            "studio/roles/*.md",
            "*.md",
            "*.ps1",
        ]
    paths: set[str] = set()
    for pattern in patterns:
        for path in repo_root.glob(pattern):
            if path.is_file() and "studio/state" not in path.as_posix():
                paths.add(path.relative_to(repo_root).as_posix())
    ordered = sorted(paths)
    if scope == "all" and len(ordered) > 80:
        return ordered[:80]
    return ordered


def _proposed_new_paths(builder_output: str) -> set[str]:
    paths: set[str] = set()
    lines = builder_output.splitlines()
    for line in lines:
        lower = line.lower()
        marks_new = (
            "(new)" in lower
            or lower.rstrip().endswith(" new")
            or "new file mode" in lower
            or ("created" in lower and "placeholder" in lower)
        )
        if not marks_new:
            continue
        for match in re.findall(r"`([^`]+)`", line):
            cleaned = match.strip()
            if _looks_like_repo_path(cleaned) and not cleaned.startswith("."):
                paths.add(cleaned)
    for index, line in enumerate(lines):
        if not line.startswith("+++ b/"):
            continue
        context = "\n".join(lines[max(0, index - 3) : index])
        if "new file mode" not in context:
            continue
        path = line.removeprefix("+++ b/").strip()
        if _looks_like_repo_path(path):
            paths.add(path)
    return paths


def _lint_builder_proposal(repo_root: Path, builder_output: str) -> list[str]:
    issues: list[str] = []
    seen_issues: set[str] = set()
    npm_scripts = _known_npm_scripts(repo_root)
    new_paths = _proposed_new_paths(builder_output)
    for line in builder_output.splitlines():
        normalized = line.strip()
        lower = normalized.lower()
        if "test commands run" in lower or "tests run" in lower:
            if "not run" not in lower and "to run later" not in lower:
                _append_issue(issues, seen_issues, "Builder proposal claims tests were run in proposal-only mode.")
        command = _extract_shell_command(normalized)
        if command:
            for issue in _lint_shell_command(command, npm_scripts):
                _append_issue(issues, seen_issues, issue)
        for proposed_path in re.findall(r"`([^`]+)`", normalized):
            proposed_path = proposed_path.strip("`").strip()
            if _is_shell_command(proposed_path):
                for issue in _lint_shell_command(proposed_path, npm_scripts):
                    _append_issue(issues, seen_issues, issue)
                continue
            if proposed_path.startswith("."):
                continue
            if not _looks_like_repo_path(proposed_path):
                continue
            if proposed_path.endswith("/"):
                continue
            if proposed_path in new_paths:
                continue
            if "new" in lower:
                continue
            if not (repo_root / proposed_path).is_file():
                _append_issue(issues, seen_issues, f"Builder proposal references a non-existent path: {proposed_path}")
    return issues


def _append_issue(issues: list[str], seen_issues: set[str], issue: str) -> None:
    if issue not in seen_issues:
        seen_issues.add(issue)
        issues.append(issue)


def _extract_shell_command(line: str) -> str | None:
    stripped = line.strip()
    if not stripped or stripped.startswith(("#", "```")):
        return None
    for match in re.finditer(r"`([^`]+)`", stripped):
        candidate = match.group(1).strip()
        if _is_shell_command(candidate):
            return _normalize_shell_command(candidate)
    stripped = stripped.lstrip("-*").strip().strip("`").strip()
    if _is_shell_command(stripped):
        return _normalize_shell_command(stripped)
    return None


def _normalize_shell_command(command: str) -> str:
    def clean(part: str) -> str:
        return part.strip("`").rstrip(":;,.")

    return " ".join(clean(part) for part in command.strip().strip("`").split())


def _is_shell_command(value: str) -> bool:
    return value.strip("`").startswith(("npm ", "npx ", "python ", "python3 ", "playwright ", "vitest ", "tsc "))


def _lint_shell_command(command: str, npm_scripts: set[str]) -> list[str]:
    tokens = _normalize_shell_command(command).split()
    if not tokens:
        return []
    executable = tokens[0]
    if executable == "npm":
        return _lint_npm_command(tokens, npm_scripts)
    if executable == "npx":
        return _lint_npx_command(tokens)
    if executable in {"playwright", "vitest", "tsc"}:
        return []
    if executable in {"python", "python3"}:
        if tokens[:3] == [executable, "-m", "unittest"]:
            return []
        return [f"Unsupported Python command: {' '.join(tokens[:3])}"]
    return []


def _lint_npm_command(tokens: list[str], npm_scripts: set[str]) -> list[str]:
    if len(tokens) < 2:
        return ["Incomplete npm command in Builder proposal."]
    command = tokens[1]
    if command == "run":
        if len(tokens) < 3:
            return ["Incomplete npm run command in Builder proposal."]
        script = tokens[2]
        if script not in npm_scripts:
            return [f"Unknown npm script in Builder proposal: {script}"]
        return []
    if command == "test":
        if "test" not in npm_scripts:
            return ["Builder proposal recommends npm test, but game/package.json has no test script."]
        return []
    if command in {"ci", "install"}:
        return []
    return [f"Unsupported npm command: npm {command}"]


def _lint_npx_command(tokens: list[str]) -> list[str]:
    if len(tokens) < 2:
        return ["Incomplete npx command in Builder proposal."]
    tool = tokens[1]
    if tool in {"playwright", "vitest", "tsc"}:
        return []
    return [f"Unsupported npx command: npx {tool}"]


def _known_npm_scripts(repo_root: Path) -> set[str]:
    package_json = repo_root / "game" / "package.json"
    if not package_json.is_file():
        return set()
    data = json.loads(package_json.read_text(encoding="utf-8"))
    scripts = data.get("scripts", {})
    if not isinstance(scripts, dict):
        return set()
    return {str(name) for name in scripts}


def _known_test_commands(repo_root: Path) -> list[str]:
    scripts = _known_npm_scripts(repo_root)
    commands: list[str] = []
    if "test" in scripts:
        commands.append("npm test")
    for script in ("typecheck", "build", "smoke"):
        if script in scripts:
            commands.append(f"npm run {script}")
    commands.extend(["python -m unittest discover -s studio/tests", "python -m unittest discover -s eval_lab/tests"])
    return commands


def _looks_like_repo_path(value: str) -> bool:
    if value.startswith(("http://", "https://")):
        return False
    if any(character.isspace() for character in value):
        return False
    return "/" in value or "\\" in value


def _read_existing_reviewer(path: Path) -> tuple[str, list[str]] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    verdict = str(data.get("verdict", "")).strip()
    if verdict not in {"PASS", "REWORK"}:
        return None
    issues = [str(issue) for issue in data.get("issues", [])]
    return verdict, issues


def _run_local_game_build_gate(repo_root: Path) -> list[str]:
    game_dir = repo_root / "game"
    if not (game_dir / "package.json").is_file() or not (game_dir / "node_modules").is_dir():
        return []
    executable = "npm.cmd" if os.name == "nt" else "npm"
    result = subprocess.run(
        [executable, "run", "build"],
        cwd=game_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        return []
    output = (result.stderr or result.stdout).strip()
    tail = " | ".join(line.strip() for line in output.splitlines()[-3:] if line.strip())
    return [f"Local npm run build failed after apply: {tail or 'non-zero exit'}"]


def _suggested_write_objective(state_dir: Path, *, before_cycle: int) -> str | None:
    notes = recent_blocker_notes(state_dir, before_cycle=before_cycle).lower()
    if "patch validation" not in notes and "diff validation" not in notes and "builder diff validation" not in notes:
        return None
    return "Increase player starting hp from 10 to 15 in game/src/engine.ts createGame()."


def _is_verification_only_objective(objective: str) -> bool:
    lowered = objective.strip().lower()
    if lowered == DEFAULT_OBJECTIVE.lower():
        return True
    markers = (
        "verify that",
        "remains playable",
        "verification only",
        "no code change",
        "without code change",
        "without modifying",
        "baseline playability",
    )
    return any(marker in lowered for marker in markers)


def _is_verification_only_designer_spec(text: str) -> bool:
    lowered = text.lower()
    strong_markers = (
        "verification baseline",
        "establishes a verification",
        "no new gameplay",
        "no gameplay mechanics",
        "no code changes are introduced",
        "remain unchanged to maintain baseline",
        "all other files remain unchanged",
    )
    if any(marker in lowered for marker in strong_markers):
        return True
    soft_markers = (
        "confirm that compilation",
        "green test results",
        "baseline stability",
        "ensuring existing tests pass",
    )
    return sum(marker in lowered for marker in soft_markers) >= 2


def _objective_from_director_output(output: str) -> str:
    for line in output.splitlines():
        normalized = line.strip().lstrip("-*").strip()
        normalized = re.sub(r"^\*\*(.+?)\*\*$", r"\1", normalized)
        normalized = re.sub(r"\*\*", "", normalized).strip()
        if not normalized:
            continue
        lowered = normalized.lower()
        if lowered.startswith("objective:"):
            return normalized.split(":", 1)[1].strip()
        if lowered.startswith("next objective:"):
            return normalized.split(":", 1)[1].strip()
        return normalized
    return DEFAULT_OBJECTIVE


if __name__ == "__main__":
    sys.exit(main())
