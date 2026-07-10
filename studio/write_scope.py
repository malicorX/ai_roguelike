from __future__ import annotations

import re

from studio.churn_guards import in_scope_paths_from_designer_spec, normalize_repo_path


def implementation_paths_from_designer(designer_output: str) -> list[str]:
    paths: list[str] = []
    for path in in_scope_paths_from_designer_spec(designer_output):
        normalized = normalize_repo_path(path)
        if normalized.startswith("game/src/") or normalized.startswith("game/smoke/"):
            paths.append(normalized)
    return paths


def test_paths_from_designer(designer_output: str) -> list[str]:
    return [
        normalize_repo_path(path)
        for path in in_scope_paths_from_designer_spec(designer_output)
        if normalize_repo_path(path).startswith("game/tests/")
    ]


def test_paths_from_acceptance_criteria(designer_output: str) -> list[str]:
    section = _designer_section(
        designer_output,
        section_names=("acceptance criteria",),
        stop_before=("in-scope", "out of scope", "test plan"),
    )
    if not section:
        return []
    seen: set[str] = set()
    paths: list[str] = []
    for match in re.findall(r"`(game/tests/[^`]+)`", section):
        normalized = normalize_repo_path(match)
        if normalized not in seen:
            seen.add(normalized)
            paths.append(normalized)
    return paths


def primary_implementation_path(designer_output: str) -> str | None:
    impl = implementation_paths_from_designer(designer_output)
    return impl[0] if impl else None


def validate_designer_spec_consistency(designer_output: str) -> list[str]:
    in_scope = set(_explicit_in_scope_paths(designer_output))
    issues: list[str] = []
    for test_path in test_paths_from_acceptance_criteria(designer_output):
        if test_path not in in_scope:
            issues.append(
                f"Acceptance criteria references `{test_path}` but In-scope files does not list it."
            )
    return issues


def validate_write_scope(designer_output: str) -> list[str]:
    impl = implementation_paths_from_designer(designer_output)
    issues: list[str] = []
    if len(impl) > 3:
        issues.append(
            "Designer spec lists more than three implementation files; proposal bundles must stay small enough for one reviewable branch."
        )
    issues.extend(validate_designer_spec_consistency(designer_output))
    return issues


def allowed_builder_paths(designer_output: str) -> set[str] | None:
    allowed: set[str] = set()
    primary = primary_implementation_path(designer_output)
    if primary:
        allowed.add(primary)
    for path in in_scope_paths_from_designer_spec(designer_output):
        normalized = normalize_repo_path(path)
        if normalized.startswith("NEW:"):
            continue
        if normalized.startswith("game/src/") or normalized.startswith("game/smoke/"):
            allowed.add(normalized)
    for path in test_paths_from_designer(designer_output):
        allowed.add(path)
    for path in test_paths_from_acceptance_criteria(designer_output):
        allowed.add(path)
    if allowed:
        return allowed
    return None


def _designer_section(
    text: str,
    *,
    section_names: tuple[str, ...],
    stop_before: tuple[str, ...],
) -> str:
    lines: list[str] = []
    in_section = False
    for line in text.splitlines():
        stripped = line.strip()
        lowered = stripped.lower()
        if not in_section:
            if any(name in lowered for name in section_names) and _is_section_header(stripped):
                in_section = True
            continue
        if any(marker in lowered for marker in stop_before) and _is_section_header(stripped):
            break
        lines.append(line)
    return "\n".join(lines)


def _explicit_in_scope_paths(text: str) -> list[str]:
    paths: list[str] = []
    in_section = False
    for line in text.splitlines():
        stripped = line.strip()
        lowered = stripped.lower()
        if _is_in_scope_section_header(lowered):
            in_section = True
            continue
        if in_section and _is_out_of_scope_section_header(lowered):
            break
        if not in_section:
            continue
        match = re.search(r"`([^`]+)`", stripped)
        if not match:
            continue
        candidate = normalize_repo_path(match.group(1))
        if candidate.startswith("new:"):
            candidate = normalize_repo_path(candidate.removeprefix("new:").strip())
        if "/" in candidate:
            paths.append(candidate)
    return paths


def _is_section_header(stripped: str) -> bool:
    return stripped.startswith("**") or stripped.startswith("#") or bool(re.match(r"^\d+\.", stripped))


def _is_in_scope_section_header(lowered: str) -> bool:
    if "in-scope" not in lowered or "files" not in lowered:
        return False
    if lowered.startswith("3."):
        return True
    return lowered.startswith("**") or bool(re.match(r"^#+\s", lowered))


def _is_out_of_scope_section_header(lowered: str) -> bool:
    if "out of scope" not in lowered:
        return False
    if lowered.startswith("4."):
        return True
    return lowered.startswith("**") or bool(re.match(r"^#+\s", lowered))
