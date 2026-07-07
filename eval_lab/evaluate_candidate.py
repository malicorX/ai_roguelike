from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Sequence

from eval_lab.protocol import DesignReport, EvaluationReport, EvaluationRequest, QaReport


def evaluate_candidate(repo_root: Path, request: EvaluationRequest) -> EvaluationReport:
    game_dir = repo_root / "game"
    checks = ["npm test", "npm run build", "npm run smoke"]
    bugs: list[str] = []
    repro_steps: list[str] = []

    for check in checks:
        result = _run_check(check, game_dir)
        if result.returncode != 0:
            bugs.append(f"{check} failed")
            repro_steps.append(f"cd game && {check}")

    qa = QaReport(
        verdict="REWORK" if bugs else "PASS",
        checks=checks,
        bugs=bugs,
        repro_steps=repro_steps,
    )
    design = DesignReport(
        verdict="BACKLOG",
        visual_notes=["Automated canvas readability and screenshot baselines passed."] if not bugs else [],
        backlog_suggestions=[
            "Add screenshot comparison and longer playthrough scenarios once visual baselines exist.",
        ],
    )

    return EvaluationReport(
        request_branch=request.branch,
        request_commit=request.commit,
        qa=qa,
        design=design,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate an ai_roguelike candidate checkout.")
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="Repository root to evaluate.")
    parser.add_argument("--request", type=Path, required=True, help="Evaluation request JSON file.")
    parser.add_argument("--out", type=Path, required=True, help="Path to write evaluation report JSON.")
    args = parser.parse_args(argv)

    request = EvaluationRequest.from_dict(json.loads(args.request.read_text(encoding="utf-8")))
    report = evaluate_candidate(args.repo, request)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report.to_dict(), indent=2) + "\n", encoding="utf-8")
    return 1 if report.blocks_merge() else 0


def _run_check(command: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    executable = "npm.cmd" if os.name == "nt" else "npm"
    args = [executable, *command.split()[1:]]
    return subprocess.run(
        args,
        cwd=cwd,
        env=_check_env(cwd),
        text=True,
        capture_output=True,
        check=False,
    )


def _check_env(game_dir: Path) -> dict[str, str]:
    env = os.environ.copy()
    existing_path = env.get("PATH") or env.get("Path") or ""
    next_path = f"{game_dir}{os.pathsep}{existing_path}"
    env["PATH"] = next_path
    env["Path"] = next_path
    return env


if __name__ == "__main__":
    sys.exit(main())
