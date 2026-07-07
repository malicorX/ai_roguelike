from __future__ import annotations

import re
import subprocess
from pathlib import Path


class GitOperationError(RuntimeError):
    pass


def slugify_objective(objective: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", objective.lower()).strip("-")
    return slug[:40] or "change"


def current_branch(repo_root: Path) -> str:
    return _git_output(repo_root, "rev-parse", "--abbrev-ref", "HEAD")


def current_short_commit(repo_root: Path) -> str:
    return _git_output(repo_root, "rev-parse", "--short", "HEAD")


def create_cycle_branch(repo_root: Path, cycle_number: int, objective: str) -> str:
    branch = f"cycle-{cycle_number:04d}-{slugify_objective(objective)}"
    _run_git(repo_root, "checkout", "-b", branch)
    return branch


def stage_all_and_commit(repo_root: Path, message: str) -> str:
    _run_git(repo_root, "add", "-A")
    if _git_output(repo_root, "status", "--porcelain") == "":
        raise GitOperationError("No changes to commit after applying the Builder diff.")
    _run_git(repo_root, "commit", "-m", message)
    return current_short_commit(repo_root)


def changed_files_against_main(repo_root: Path) -> list[str]:
    output = _git_output(repo_root, "diff", "--name-only", "main...HEAD")
    return [line.strip() for line in output.splitlines() if line.strip()]


def merge_branch_to_main(repo_root: Path, branch: str, *, message: str) -> None:
    _run_git(repo_root, "checkout", "main")
    _run_git(repo_root, "merge", "--no-ff", "-m", message, branch)


def discard_branch(repo_root: Path, branch: str) -> None:
    active = current_branch(repo_root)
    if active == branch:
        _run_git(repo_root, "checkout", "main")
    _run_git(repo_root, "branch", "-D", branch)


def push_branch(repo_root: Path, branch: str) -> None:
    _run_git(repo_root, "push", "-u", "origin", branch)


def push_main(repo_root: Path) -> None:
    _run_git(repo_root, "push", "origin", "main")


def _run_git(repo_root: Path, *args: str) -> None:
    result = subprocess.run(["git", *args], cwd=repo_root, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise GitOperationError(detail or f"git {' '.join(args)} failed")


def _git_output(repo_root: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=repo_root, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise GitOperationError(detail or f"git {' '.join(args)} failed")
    return result.stdout.strip()
