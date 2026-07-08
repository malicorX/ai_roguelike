from __future__ import annotations

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


def primary_implementation_path(designer_output: str) -> str | None:
    impl = implementation_paths_from_designer(designer_output)
    return impl[0] if impl else None


def validate_write_scope(designer_output: str) -> list[str]:
    impl = implementation_paths_from_designer(designer_output)
    tests = test_paths_from_designer(designer_output)
    issues: list[str] = []
    if len(impl) > 1:
        issues.append(
            "Designer spec lists more than one implementation file; write mode allows one "
            "game/src/ or game/smoke/ file per cycle."
        )
    if impl and tests:
        issues.append(
            "Designer spec mixes implementation and test files in one cycle; put test updates "
            "out of scope and let sparky2 catch regressions first."
        )
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
    if allowed:
        return allowed
    return None
