from __future__ import annotations

import re
import subprocess
from pathlib import Path


class PatchApplyError(RuntimeError):
    pass


class PatchExtractError(RuntimeError):
    pass


def extract_unified_diff(text: str) -> str:
    for match in re.finditer(r"```(?:\w+)?\s*\n(.*?)```", text, re.DOTALL | re.IGNORECASE):
        candidate = match.group(1).strip()
        if _looks_like_unified_diff(candidate):
            return candidate + "\n"
    stripped = text.strip()
    if _looks_like_unified_diff(stripped):
        return stripped + ("\n" if not stripped.endswith("\n") else "")
    raise PatchExtractError("Builder output did not include a unified diff fenced block.")


def _looks_like_unified_diff(candidate: str) -> bool:
    return candidate.startswith("diff --git") or candidate.startswith("--- ")


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
    seen: set[str] = set()
    for line in diff.splitlines():
        path: str | None = None
        if line.startswith("diff --git "):
            match = re.match(r"diff --git a/(.+?) b/(.+)$", line)
            if match:
                path = match.group(2)
        elif line.startswith("--- a/"):
            match = re.match(r"--- a/(.+)$", line)
            if match:
                path = match.group(1)
        if path and path not in seen:
            seen.add(path)
            paths.append(path)
    return paths
