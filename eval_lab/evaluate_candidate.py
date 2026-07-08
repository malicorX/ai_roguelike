from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Sequence

from eval_lab.design_review import run_design_review
from eval_lab.protocol import DesignReport, EvaluationReport, EvaluationRequest, QaReport


def evaluate_candidate(repo_root: Path, request: EvaluationRequest) -> EvaluationReport:
    game_dir = repo_root / "game"
    checks = ["npm test", "npm run build", "npm run smoke"]
    bugs: list[str] = []
    repro_steps: list[str] = []
    previous_head = _checkout_candidate(repo_root, request)

    try:
        for check in checks:
            result = _run_check(check, game_dir)
            if result.returncode != 0:
                bugs.append(f"{check} failed")
                repro_steps.append(f"cd game && {check}")
    finally:
        if previous_head is not None:
            _run_git(repo_root, "checkout", previous_head)

    qa = QaReport(
        verdict="REWORK" if bugs else "PASS",
        checks=checks,
        bugs=bugs,
        repro_steps=repro_steps,
    )
    design = run_design_review(repo_root, request, roles_dir=repo_root / "studio" / "roles", qa_passed=not bugs)

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


def _checkout_candidate(repo_root: Path, request: EvaluationRequest) -> str | None:
    if not (repo_root / ".git").exists():
        return None
    previous_branch = _git_output(repo_root, "rev-parse", "--abbrev-ref", "HEAD")
    restore_ref = previous_branch if previous_branch != "HEAD" else _git_output(repo_root, "rev-parse", "HEAD")
    if request.branch == previous_branch and request.commit == _git_output(repo_root, "rev-parse", "--short", "HEAD"):
        return None
    if request.branch == "main" and previous_branch == "main" and request.commit == _git_output(repo_root, "rev-parse", "--short", "HEAD"):
        return None

    subprocess.run(["git", "fetch", "-q", "origin"], cwd=repo_root, check=False)
    for ref in (request.commit, request.branch):
        result = subprocess.run(["git", "checkout", ref], cwd=repo_root, capture_output=True, text=True, check=False)
        if result.returncode == 0:
            return restore_ref
    raise RuntimeError(f"Unable to checkout candidate {request.branch}@{request.commit}")


def _git_output(repo_root: Path, *args: str) -> str:
    return _run_git(repo_root, *args).stdout.strip()


def _run_git(repo_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(["git", *args], cwd=repo_root, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(detail or f"git {' '.join(args)} failed")
    return result


if __name__ == "__main__":
    sys.exit(main())
