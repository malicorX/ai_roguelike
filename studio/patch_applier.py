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
    repaired = repair_unified_diff(repo_root, diff)
    apply_flags = ["--whitespace=nowarn"]
    check = subprocess.run(
        ["git", "apply", "--check", *apply_flags, "-"],
        cwd=repo_root,
        input=repaired,
        text=True,
        capture_output=True,
        check=False,
    )
    if check.returncode != 0:
        recount_check = subprocess.run(
            ["git", "apply", "--check", "--recount", *apply_flags, "-"],
            cwd=repo_root,
            input=repaired,
            text=True,
            capture_output=True,
            check=False,
        )
        if recount_check.returncode == 0:
            apply_flags.append("--recount")
        else:
            relaxed_check = subprocess.run(
                ["git", "apply", "--check", "--ignore-whitespace", *apply_flags, "-"],
                cwd=repo_root,
                input=repaired,
                text=True,
                capture_output=True,
                check=False,
            )
            if relaxed_check.returncode == 0:
                apply_flags.append("--ignore-whitespace")
            else:
                raise PatchApplyError(
                    check.stderr.strip() or recount_check.stderr.strip() or relaxed_check.stderr.strip() or "git apply --check failed."
                )

    apply = subprocess.run(
        ["git", "apply", *apply_flags, "-"],
        cwd=repo_root,
        input=repaired,
        text=True,
        capture_output=True,
        check=False,
    )
    if apply.returncode != 0:
        raise PatchApplyError(apply.stderr.strip() or "git apply failed.")


def repair_unified_diff(repo_root: Path, diff: str) -> str:
    lines = diff.splitlines()
    output: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith("diff --git ") or line.startswith("index "):
            output.append(line)
            index += 1
            continue
        if line.startswith("--- "):
            old_path = _diff_path_from_header(line)
            if index + 1 >= len(lines) or not lines[index + 1].startswith("+++ "):
                output.append(line)
                index += 1
                continue
            new_path = _diff_path_from_header(lines[index + 1])
            output.append(f"--- a/{old_path}")
            output.append(f"+++ b/{new_path}")
            index += 2
            source_lines = _read_repo_lines(repo_root, old_path)
            while index < len(lines) and not lines[index].startswith("--- ") and not lines[index].startswith("diff --git "):
                if not lines[index].startswith("@@"):
                    output.append(lines[index])
                    index += 1
                    continue
                header = lines[index]
                index += 1
                body: list[str] = []
                while index < len(lines) and not lines[index].startswith("@@") and not lines[index].startswith("--- ") and not lines[index].startswith("diff --git "):
                    body.append(lines[index])
                    index += 1
                output.extend(_repair_hunk(source_lines, header, body))
            continue
        output.append(line)
        index += 1
    return "\n".join(output) + ("\n" if diff.endswith("\n") else "")


def _diff_path_from_header(header: str) -> str:
    match = re.match(r"^[+-]{3} [ab]/(.*)$", header)
    if not match:
        raise PatchApplyError(f"Invalid diff header: {header}")
    return match.group(1)


def _read_repo_lines(repo_root: Path, rel_path: str) -> list[str]:
    source = repo_root / rel_path
    if not source.is_file():
        raise PatchApplyError(f"Diff targets missing file: {rel_path}")
    return source.read_text(encoding="utf-8").splitlines()


def _repair_hunk(source_lines: list[str], header: str, body: list[str]) -> list[str]:
    old_pattern = [line[1:] for line in body if line.startswith(" ") or line.startswith("-")]
    if not old_pattern:
        return [header, *body]

    start = _find_subsequence(source_lines, old_pattern)
    if start is None:
        return [header, *body]

    old_count = sum(1 for line in body if line.startswith(" ") or line.startswith("-"))
    new_count = sum(1 for line in body if line.startswith(" ") or line.startswith("+"))
    context = ""
    match = re.match(r"@@ [^@]+ @@(.*)$", header)
    if match and match.group(1):
        context = f" {match.group(1).strip()}"
    repaired_header = f"@@ -{start + 1},{old_count} +{start + 1},{new_count} @@{context}"
    return [repaired_header, *body]


def _find_subsequence(haystack: list[str], needle: list[str]) -> int | None:
    if not needle:
        return None
    limit = len(haystack) - len(needle) + 1
    for start in range(limit):
        if haystack[start : start + len(needle)] == needle:
            return start
    return None


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
