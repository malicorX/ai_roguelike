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


def validate_unified_diff(repo_root: Path, diff: str) -> list[str]:
    issues: list[str] = []
    try:
        repaired = repair_unified_diff(repo_root, diff)
    except PatchApplyError as exc:
        return [str(exc)]

    for file_patch in _iter_file_patches(repaired):
        lines = [line for line in file_patch.splitlines() if line]
        if len(lines) < 2:
            continue
        old_header = lines[0]
        new_header = lines[1]
        old_path = _diff_path_from_header(old_header)
        new_path = _diff_path_from_header(new_header)
        is_new_file = old_header.strip() == "--- /dev/null" or not (repo_root / old_path).is_file()
        if is_new_file:
            continue
        source_lines = _read_repo_lines(repo_root, new_path)
        index = 2
        hunk_number = 0
        while index < len(lines):
            if not lines[index].startswith("@@"):
                index += 1
                continue
            hunk_number += 1
            index += 1
            body: list[str] = []
            while index < len(lines) and not lines[index].startswith("@@"):
                body.append(lines[index])
                index += 1
            old_pattern = [line[1:] for line in body if line.startswith(" ") or line.startswith("-")]
            if old_pattern and _find_subsequence(source_lines, old_pattern) is None:
                preview = old_pattern[0][:80]
                issues.append(f"Hunk {hunk_number} context not found in {new_path}: {preview!r}")
    return issues


def apply_unified_diff(repo_root: Path, diff: str) -> None:
    repaired = repair_unified_diff(repo_root, diff)
    file_patches = list(_iter_file_patches(repaired))
    if not file_patches:
        raise PatchApplyError("Diff did not include any file sections.")
    for file_patch in file_patches:
        _apply_file_patch(repo_root, file_patch)


def _iter_file_patches(repaired: str):
    lines = repaired.splitlines()
    current: list[str] = []
    for line in lines:
        if line.startswith("diff --git ") or line.startswith("index "):
            continue
        if line.startswith("--- "):
            if current:
                yield "\n".join(current) + "\n"
            current = [line]
            continue
        if current:
            current.append(line)
    if current:
        yield "\n".join(current) + "\n"


def _apply_file_patch(repo_root: Path, file_patch: str) -> None:
    lines = [line for line in file_patch.splitlines() if line]
    if len(lines) < 2 or not lines[0].startswith("--- ") or not lines[1].startswith("+++ "):
        raise PatchApplyError("Invalid file patch section.")

    old_header = lines[0]
    new_header = lines[1]
    old_path = _diff_path_from_header(old_header)
    new_path = _diff_path_from_header(new_header)
    is_new_file = old_header.strip() == "--- /dev/null" or not (repo_root / old_path).is_file()

    index = 2
    while index < len(lines):
        if not lines[index].startswith("@@"):
            index += 1
            continue
        header = lines[index]
        index += 1
        body: list[str] = []
        while index < len(lines) and not lines[index].startswith("@@"):
            body.append(lines[index])
            index += 1

        file_exists = (repo_root / new_path).is_file()
        source_lines = _read_repo_lines(repo_root, new_path) if file_exists else []
        hunk_lines = _repair_hunk(source_lines, header, body) if file_exists else [header, *body]
        if file_exists:
            patch = "\n".join([f"--- a/{new_path}", f"+++ b/{new_path}", *hunk_lines]) + "\n"
        else:
            patch = "\n".join(["--- /dev/null", f"+++ b/{new_path}", *hunk_lines]) + "\n"
        _git_apply_with_fallback(repo_root, patch)


def _git_apply_with_fallback(repo_root: Path, patch: str) -> None:
    apply_flags = ["--whitespace=nowarn"]
    check = subprocess.run(
        ["git", "apply", "--check", *apply_flags, "-"],
        cwd=repo_root,
        input=patch,
        text=True,
        capture_output=True,
        check=False,
    )
    if check.returncode != 0:
        recount_check = subprocess.run(
            ["git", "apply", "--check", "--recount", *apply_flags, "-"],
            cwd=repo_root,
            input=patch,
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
                input=patch,
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
        input=patch,
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
            if index + 1 >= len(lines) or not lines[index + 1].startswith("+++ "):
                output.append(line)
                index += 1
                continue
            old_header = line
            new_header = lines[index + 1]
            old_path = _diff_path_from_header(old_header)
            new_path = _diff_path_from_header(new_header)
            is_new_file = old_header.strip() == "--- /dev/null" or not (repo_root / old_path).is_file()
            if is_new_file:
                output.append("--- /dev/null")
                output.append(f"+++ b/{new_path}")
            else:
                output.append(f"--- a/{old_path}")
                output.append(f"+++ b/{new_path}")
            index += 2
            source_lines = [] if is_new_file else _read_repo_lines(repo_root, old_path)
            pending_context: list[str] = []
            while index < len(lines) and not lines[index].startswith("--- ") and not lines[index].startswith("diff --git "):
                if not lines[index].startswith("@@"):
                    if lines[index] and lines[index][0] in " +-":
                        pending_context.append(lines[index])
                        index += 1
                        continue
                    if pending_context:
                        output.extend(_repair_hunk(source_lines, "@@ -1,0 +1,0 @@", pending_context))
                        pending_context = []
                    output.append(lines[index])
                    index += 1
                    continue
                header = lines[index]
                index += 1
                body: list[str] = list(pending_context)
                pending_context = []
                while index < len(lines) and not lines[index].startswith("@@") and not lines[index].startswith("--- ") and not lines[index].startswith("diff --git "):
                    if lines[index] and lines[index][0] in " +-":
                        body.append(lines[index])
                        index += 1
                    else:
                        break
                full_body = list(body)
                body = _trim_trailing_context_after_edits(full_body)
                if is_new_file:
                    output.extend([header, *body])
                else:
                    output.extend(_repair_hunk(source_lines, header, body))
            if pending_context:
                if is_new_file:
                    output.extend(["@@ -0,0 +1,0 @@", *pending_context])
                else:
                    output.extend(_repair_hunk(source_lines, "@@ -1,0 +1,0 @@", pending_context))
            continue
        output.append(line)
        index += 1
    return "\n".join(output) + ("\n" if diff.endswith("\n") else "")


def _diff_path_from_header(header: str) -> str:
    if header.strip() == "--- /dev/null":
        return "/dev/null"
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
    body = [line for line in body if line not in {"+", "-"}]
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


def _trim_trailing_context_after_edits(body: list[str], *, max_trailing_context: int = 3) -> list[str]:
    last_change = -1
    for index, line in enumerate(body):
        if line.startswith(("+", "-")):
            last_change = index
    if last_change < 0:
        return body

    end = last_change + 1
    kept_after = 0
    for index in range(last_change + 1, len(body)):
        line = body[index]
        if line.startswith(" ") and kept_after < max_trailing_context:
            end = index + 1
            kept_after += 1
        else:
            break
    return body[:end]


def _find_subsequence(haystack: list[str], needle: list[str]) -> int | None:
    if not needle:
        return None
    limit = len(haystack) - len(needle) + 1
    for start in range(limit):
        if haystack[start : start + len(needle)] == needle:
            return start
    normalized_haystack = [line.strip() for line in haystack]
    normalized_needle = [line.strip() for line in needle]
    for start in range(len(normalized_haystack) - len(normalized_needle) + 1):
        if normalized_haystack[start : start + len(normalized_needle)] == normalized_needle:
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
