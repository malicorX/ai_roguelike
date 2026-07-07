from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from eval_lab.evaluate_candidate import evaluate_candidate
from eval_lab.protocol import EvaluationReport, EvaluationRequest
from studio.config import StudioConfig

DEFAULT_OBJECTIVE = "Verify that the current v0 game remains playable."
DEFAULT_SPEC = "Run deterministic unit, build, and browser smoke gates before any autonomous code changes."
DEFAULT_SEEDS = [1, 7, 42]
DEFAULT_FOCUS = ["qa", "browser-smoke", "visual-readability"]


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
) -> DryCycleResult:
    state_dir.mkdir(parents=True, exist_ok=True)
    request = build_evaluation_request(repo_root, objective=objective, spec=spec)
    report = evaluate_candidate(repo_root, request)

    request_path = state_dir / f"cycle-{cycle_number:04d}-request.json"
    report_path = state_dir / f"cycle-{cycle_number:04d}-report.json"
    request_path.write_text(json.dumps(request.to_dict(), indent=2) + "\n", encoding="utf-8")
    report_path.write_text(json.dumps(report.to_dict(), indent=2) + "\n", encoding="utf-8")

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
    parser.add_argument("--dry-run", action="store_true", help="Run one safe local evaluation cycle.")
    args = parser.parse_args(argv)

    StudioConfig.from_model_string(args.models)
    state_dir = args.state_dir or args.repo_root / "studio" / "state"

    if not args.dry_run:
        print("Full autonomous loop is not enabled yet. Re-run with --dry-run for the current safe Phase 0 path.")
        return 2

    cycles = max(1, args.max_cycles)
    last_result: DryCycleResult | None = None
    for cycle_number in range(1, cycles + 1):
        last_result = run_dry_cycle(args.repo_root, state_dir, cycle_number=cycle_number)
        print(f"cycle {cycle_number}: report={last_result.report_path} blocked={last_result.blocked}")

    return 1 if last_result and last_result.blocked else 0


def _git_output(repo_root: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", *args],
        cwd=repo_root,
        text=True,
        stderr=subprocess.DEVNULL,
    ).strip()


if __name__ == "__main__":
    sys.exit(main())
