from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Callable, Sequence

from eval_lab.protocol import EvaluationRequest
from studio.config import StudioConfig
from studio.evaluation_client import EvaluationClient, EvaluationTarget
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


def build_evaluation_request(
    repo_root: Path,
    *,
    objective: str,
    spec: str,
    changed_files: list[str] | None = None,
) -> EvaluationRequest:
    return EvaluationRequest(
        branch=_git_output(repo_root, "rev-parse", "--abbrev-ref", "HEAD"),
        commit=_git_output(repo_root, "rev-parse", "--short", "HEAD"),
        objective=objective,
        spec=spec,
        changed_files=changed_files or [],
        seeds=list(DEFAULT_SEEDS),
        focus=list(DEFAULT_FOCUS),
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
        director_output = role_runner(
            studio_config,
            roles_dir,
            "director",
            _director_context(repo_root, objective=objective, spec=spec),
            timeout_seconds=role_timeout_seconds,
        )
        (state_dir / f"cycle-{cycle_number:04d}-director.md").write_text(director_output.rstrip() + "\n", encoding="utf-8")
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
    args = parser.parse_args(argv)

    studio_config = StudioConfig.from_model_string(args.models)
    state_dir = args.state_dir or args.repo_root / "studio" / "state"
    evaluation_target = EvaluationTarget(args.evaluation_target)
    director_mode = DirectorMode(args.director_mode)

    if not args.dry_run:
        print("Full autonomous loop is not enabled yet. Re-run with --dry-run for the current safe Phase 0 path.")
        return 2

    cycles = max(1, args.max_cycles)
    last_result: DryCycleResult | None = None
    for cycle_number in range(1, cycles + 1):
        last_result = run_dry_cycle(
            args.repo_root,
            state_dir,
            cycle_number=cycle_number,
            evaluation_target=evaluation_target,
            director_mode=director_mode,
            studio_config=studio_config,
            role_timeout_seconds=args.role_timeout_seconds,
        )
        print(f"cycle {cycle_number}: report={last_result.report_path} blocked={last_result.blocked}")

    return 1 if last_result and last_result.blocked else 0


def _git_output(repo_root: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", *args],
        cwd=repo_root,
        text=True,
        stderr=subprocess.DEVNULL,
    ).strip()


def _director_context(repo_root: Path, *, objective: str, spec: str) -> str:
    branch = _git_output(repo_root, "rev-parse", "--abbrev-ref", "HEAD")
    commit = _git_output(repo_root, "rev-parse", "--short", "HEAD")
    return "\n".join(
        [
            f"Branch: {branch}",
            f"Commit: {commit}",
            f"Current safe objective: {objective}",
            f"Current safe spec: {spec}",
            "Mode: no-write dry-run. Propose the next small objective only; do not request code changes yet.",
        ]
    )


def _objective_from_director_output(output: str) -> str:
    for line in output.splitlines():
        normalized = line.strip().lstrip("-*").strip()
        if not normalized:
            continue
        for prefix in ("Objective:", "Next objective:", "OBJECTIVE:"):
            if normalized.startswith(prefix):
                normalized = normalized[len(prefix) :].strip()
                break
        return normalized
    return DEFAULT_OBJECTIVE


if __name__ == "__main__":
    sys.exit(main())
