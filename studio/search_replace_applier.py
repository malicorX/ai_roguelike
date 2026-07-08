from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from studio.patch_applier import PatchExtractError, apply_unified_diff, validate_unified_diff


@dataclass(frozen=True)
class SearchReplaceEdit:
    path: str
    search: str
    replace: str


@dataclass(frozen=True)
class NewFileEdit:
    path: str
    content: str


@dataclass
class BuilderPatch:
    search_replaces: list[SearchReplaceEdit] = field(default_factory=list)
    new_files: list[NewFileEdit] = field(default_factory=list)
    unified_diff: str | None = None

    def has_edits(self) -> bool:
        return bool(self.search_replaces or self.new_files or self.unified_diff)

    def changed_paths(self) -> list[str]:
        paths: list[str] = []
        seen: set[str] = set()
        for edit in [*self.search_replaces, *self.new_files]:
            if edit.path not in seen:
                seen.add(edit.path)
                paths.append(edit.path)
        if self.unified_diff:
            from studio.patch_applier import diff_paths

            for path in diff_paths(self.unified_diff):
                if path not in seen:
                    seen.add(path)
                    paths.append(path)
        return paths


_SEARCH_REPLACE_BLOCK = re.compile(
    r"```search_replace\s+([^\s`]+)\s*\r?\n(.*?)```",
    re.DOTALL | re.IGNORECASE,
)
_NEW_FILE_BLOCK = re.compile(
    r"```new_file\s+([^\s`]+)\s*\r?\n(.*?)```",
    re.DOTALL | re.IGNORECASE,
)
_SEARCH_REPLACE_BODY = re.compile(
    r"<<<<<<< SEARCH\r?\n(.*?)=======\r?\n(.*?)>>>>>>> REPLACE",
    re.DOTALL,
)


def extract_builder_patch(text: str) -> BuilderPatch:
    search_replaces: list[SearchReplaceEdit] = []
    new_files: list[NewFileEdit] = []

    for match in _SEARCH_REPLACE_BLOCK.finditer(text):
        path = _normalize_path(match.group(1))
        body_match = _SEARCH_REPLACE_BODY.search(match.group(2))
        if body_match is None:
            raise PatchExtractError(f"search_replace block for {path} is missing SEARCH/REPLACE markers.")
        search = body_match.group(1)
        replace = body_match.group(2)
        if not search:
            raise PatchExtractError(f"search_replace block for {path} has an empty SEARCH section.")
        search_replaces.append(SearchReplaceEdit(path=path, search=search, replace=replace))

    for match in _NEW_FILE_BLOCK.finditer(text):
        path = _normalize_path(match.group(1))
        content = match.group(2)
        if not content.strip():
            raise PatchExtractError(f"new_file block for {path} is empty.")
        new_files.append(NewFileEdit(path=path, content=content.rstrip("\n") + "\n"))

    unified_diff: str | None = None
    if not search_replaces and not new_files:
        from studio.patch_applier import extract_unified_diff

        unified_diff = extract_unified_diff(text)

    return BuilderPatch(search_replaces=search_replaces, new_files=new_files, unified_diff=unified_diff)


def validate_builder_patch(
    repo_root: Path,
    patch: BuilderPatch,
    *,
    allowed_paths: set[str] | None = None,
) -> list[str]:
    if not patch.has_edits():
        return ["Builder output did not include search_replace blocks, new_file blocks, or a unified diff."]

    issues: list[str] = []
    for path in patch.changed_paths():
        if allowed_paths is not None and path not in allowed_paths:
            issues.append(f"Builder edited out-of-scope path: {path}")

    for edit in patch.search_replaces:
        source_path = repo_root / edit.path
        if not source_path.is_file():
            issues.append(f"search_replace targets missing file: {edit.path}")
            continue
        source = source_path.read_text(encoding="utf-8")
        count = source.count(edit.search)
        if count == 0:
            preview = edit.search.splitlines()[0][:80]
            issues.append(f"SEARCH text not found in {edit.path}: {preview!r}")
        elif count > 1:
            issues.append(f"SEARCH text in {edit.path} must be unique (found {count} matches).")

    for edit in patch.new_files:
        source_path = repo_root / edit.path
        if source_path.is_file():
            issues.append(f"new_file block targets existing file: {edit.path}")

    if patch.unified_diff and not patch.search_replaces and not patch.new_files:
        issues.extend(validate_unified_diff(repo_root, patch.unified_diff))

    return issues


def apply_builder_patch(repo_root: Path, patch: BuilderPatch) -> None:
    if patch.search_replaces or patch.new_files:
        for edit in patch.search_replaces:
            source_path = repo_root / edit.path
            source = source_path.read_text(encoding="utf-8")
            count = source.count(edit.search)
            if count != 1:
                raise PatchExtractError(f"Cannot apply search_replace for {edit.path}: expected 1 match, found {count}.")
            source_path.write_text(source.replace(edit.search, edit.replace, 1), encoding="utf-8")

        for edit in patch.new_files:
            target = repo_root / edit.path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(edit.content, encoding="utf-8")
        return

    if patch.unified_diff:
        apply_unified_diff(repo_root, patch.unified_diff)
        return

    raise PatchExtractError("Builder patch did not include any applicable edits.")


def _normalize_path(path: str) -> str:
    cleaned = path.strip().replace("\\", "/").lstrip("./")
    if cleaned.startswith("a/") or cleaned.startswith("b/"):
        cleaned = cleaned[2:]
    return cleaned
