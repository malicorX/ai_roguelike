from __future__ import annotations

import re
import subprocess
from pathlib import Path


class PatchApplyError(RuntimeError):
    pass


class PatchExtractError(RuntimeError):
    pass


def extract_unified_diff(text: str) -> str:
    fenced = re.search(r"```(?:diff)?\s*\n(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if fenced:
        candidate = fenced.group(1).strip()
        if candidate.startswith("diff --git") or candidate.startswith("--- "):
            return candidate + "\n"
    stripped = text.strip()
    if stripped.startswith("diff --git") or stripped.startswith("--- "):
        return stripped + ("\n" if not stripped.endswith("\n") else "")
    raise PatchExtractError("Builder output did not include a unified diff fenced block.")


def apply_unified_diff(repo_root: Path, diff: str) -> None:
    check = subprocess.run(
        ["git", "apply", "--check", "--whitespace=nowarn", "-"],
        cwd=repo_root,
        input=diff,
        text=True,
        capture_output=True,
        check=False,
    )
    if check.returncode != 0:
        raise PatchApplyError(check.stderr.strip() or "git apply --check failed.")

    apply = subprocess.run(
        ["git", "apply", "--whitespace=nowarn", "-"],
        cwd=repo_root,
        input=diff,
        text=True,
        capture_output=True,
        check=False,
    )
    if apply.returncode != 0:
        raise PatchApplyError(apply.stderr.strip() or "git apply failed.")


def diff_paths(diff: str) -> list[str]:
    paths: list[str] = []
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            match = re.match(r"diff --git a/(.+?) b/(.+)$", line)
            if match:
                paths.append(match.group(2))
    return paths
