from __future__ import annotations

import json
import re
from pathlib import Path

MAX_CONSECUTIVE_TEST_ONLY_MERGES = 1

GAMEPLAY_OBJECTIVE_SEEDS = (
    "Make each enemy move one tile toward the player after every player action in game/src/engine.ts.",
    "Add a second enemy to the starting room in game/src/engine.ts createGame().",
    "Increase player starting hp from 10 to 15 in game/src/engine.ts and update game/tests/engine.test.ts.",
    "Show the enemy count on the HUD status line in game/src/main.ts.",
)

PLAYER_VISIBLE_PREFIXES = (
    "game/src/engine.ts",
    "game/src/main.ts",
    "game/src/render.ts",
)
PLAYER_VISIBLE_EXCLUDED = frozenset({"game/src/testHarness.ts"})


def normalize_repo_path(path: str) -> str:
    return path.replace("\\", "/").strip().lstrip("./")


def game_changed_files(changed_files: list[str]) -> list[str]:
    return [path for path in changed_files if normalize_repo_path(path).startswith("game/")]


def is_src_change(changed_files: list[str]) -> bool:
    return any(normalize_repo_path(path).startswith("game/src/") for path in game_changed_files(changed_files))


def is_test_only_change(changed_files: list[str]) -> bool:
    game_files = game_changed_files(changed_files)
    if not game_files:
        return False
    normalized = [normalize_repo_path(path) for path in game_files]
    return all(path.startswith("game/tests/") for path in normalized)


def has_player_visible_change(changed_files: list[str]) -> bool:
    for path in game_changed_files(changed_files):
        normalized = normalize_repo_path(path)
        if normalized in PLAYER_VISIBLE_EXCLUDED:
            continue
        if any(normalized == prefix or normalized.startswith(f"{prefix}") for prefix in PLAYER_VISIBLE_PREFIXES):
            return True
        if normalized.startswith("game/smoke/"):
            return True
    return False


def consecutive_test_only_merges(state_dir: Path, *, before_cycle: int) -> int:
    streak = 0
    for number in range(before_cycle - 1, 0, -1):
        merge_path = state_dir / f"cycle-{number:04d}-merge.json"
        if not merge_path.is_file():
            continue
        merge = _read_json(merge_path)
        if merge.get("verdict") != "MERGED":
            continue
        changed_files = _changed_files_for_cycle(state_dir, number)
        if is_test_only_change(changed_files):
            streak += 1
            continue
        break
    return streak


def requires_src_change(state_dir: Path, *, before_cycle: int) -> bool:
    return consecutive_test_only_merges(state_dir, before_cycle=before_cycle) >= MAX_CONSECUTIVE_TEST_ONLY_MERGES


def is_test_only_objective(objective: str) -> bool:
    lowered = objective.strip().lower()
    test_markers = (
        "unit test",
        "test file",
        "test for ",
        "tests for ",
        "add test",
        "create test",
        "validation test",
        "assertion",
        "strict typescript",
        "defensive array",
    )
    if not any(marker in lowered for marker in test_markers):
        return False
    if "game/src/" in lowered:
        return False
    return True


def in_scope_paths_from_designer_spec(text: str) -> list[str]:
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
        if match:
            candidate = normalize_repo_path(match.group(1))
            if candidate.startswith("new:"):
                candidate = normalize_repo_path(candidate.removeprefix("new:").strip())
            if "/" in candidate:
                paths.append(candidate)
    if paths:
        return paths
    return _fallback_repo_paths_from_designer(text)


def _is_in_scope_section_header(lowered: str) -> bool:
    if "in-scope" not in lowered or "files" not in lowered:
        return False
    if lowered.startswith("3."):
        return True
    return bool(re.match(r"^#+\s", lowered))


def _is_out_of_scope_section_header(lowered: str) -> bool:
    if "out of scope" not in lowered:
        return False
    if lowered.startswith("4."):
        return True
    return bool(re.match(r"^#+\s", lowered))


def _fallback_repo_paths_from_designer(text: str) -> list[str]:
    paths: list[str] = []
    seen: set[str] = set()
    for match in re.findall(r"`(game/(?:src|smoke|tests)/[^`]+)`", text):
        candidate = normalize_repo_path(match)
        if candidate not in seen:
            seen.add(candidate)
            paths.append(candidate)
    return paths


def is_test_only_designer_spec(text: str) -> bool:
    paths = in_scope_paths_from_designer_spec(text)
    if not paths:
        lowered = text.lower()
        if "game/tests/" in lowered and "game/src/" not in lowered:
            return True
        return False
    normalized = [normalize_repo_path(path) for path in paths]
    if any(path.startswith("game/src/") for path in normalized):
        return False
    return all(path.startswith("game/tests/") for path in normalized)


def mandatory_gameplay_objective(state_dir: Path, *, before_cycle: int) -> str | None:
    if not requires_src_change(state_dir, before_cycle=before_cycle):
        return None
    seed_index = (before_cycle - 1) % len(GAMEPLAY_OBJECTIVE_SEEDS)
    return GAMEPLAY_OBJECTIVE_SEEDS[seed_index]


def churn_director_notes(state_dir: Path, *, before_cycle: int) -> list[str]:
    streak = consecutive_test_only_merges(state_dir, before_cycle=before_cycle)
    if streak == 0:
        return []
    lines = [
        f"Recent merged cycles: {streak} consecutive test-only merge(s) (game/tests/ only).",
        "Next cycle MUST include a player-visible change under game/src/ or game/smoke/.",
        "Do NOT pick another test-only objective.",
    ]
    if mandatory := mandatory_gameplay_objective(state_dir, before_cycle=before_cycle):
        lines.extend(["", "Mandatory gameplay objective candidate:", mandatory])
    return lines


def changed_files_for_cycle(state_dir: Path, cycle_number: int) -> list[str]:
    return _changed_files_for_cycle(state_dir, cycle_number)


def _changed_files_for_cycle(state_dir: Path, cycle_number: int) -> list[str]:
    apply_path = state_dir / f"cycle-{cycle_number:04d}-apply.json"
    if apply_path.is_file():
        changed = _read_json(apply_path).get("changed_files", [])
        if isinstance(changed, list):
            return [str(path) for path in changed]
    request_path = state_dir / f"cycle-{cycle_number:04d}-request.json"
    if request_path.is_file():
        changed = _read_json(request_path).get("changed_files", [])
        if isinstance(changed, list):
            return [str(path) for path in changed]
    return []


def _read_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}
