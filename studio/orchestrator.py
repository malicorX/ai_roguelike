from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Callable, Sequence

from eval_lab.protocol import DesignReport, EvaluationReport, EvaluationRequest, QaReport
from studio.config import StudioConfig
from studio.evaluation_client import EvaluationClient, EvaluationTarget
from studio.publish_devlog import publish_site
from studio.role_runner import run_role

DEFAULT_OBJECTIVE = "Verify that the current v0 game remains playable."
DEFAULT_SPEC = "Run deterministic unit, build, and browser smoke gates before any autonomous code changes."
DEFAULT_SEEDS = [1, 7, 42]
DEFAULT_FOCUS = ["qa", "browser-smoke", "visual-readability"]
RoleRunner = Callable[..., str]


class DirectorMode(StrEnum):
    STATIC = "static"
    MODEL = "model"


@dataclass(frozen=True)
class DryCycleResult:
    request_path: Path
    report_path: Path
    blocked: bool
    blocking_reasons: list[str]


@dataclass(frozen=True)
class PilotCycleResult:
    director_path: Path
    builder_path: Path
    proposal_lint_path: Path
    request_path: Path
    report_path: Path
    blocked: bool
    blocking_reasons: list[str]


def build_evaluation_request(
    repo_root: Path,
    *,
    objective: str,
    spec: str,
    changed_files: list[str] | None = None,
) -> EvaluationRequest:
    return EvaluationRequest(
        branch=_git_output(repo_root, "rev-parse", "--abbrev-ref", "HEAD"),
        commit=_git_output(repo_root, "rev-parse", "--short", "HEAD"),
        objective=objective,
        spec=spec,
        changed_files=changed_files or [],
        seeds=list(DEFAULT_SEEDS),
        focus=list(DEFAULT_FOCUS),
    )


def run_pilot_cycle(
    repo_root: Path,
    state_dir: Path,
    *,
    objective: str = DEFAULT_OBJECTIVE,
    spec: str = DEFAULT_SPEC,
    cycle_number: int = 1,
    evaluation_target: EvaluationTarget = EvaluationTarget.LOCAL,
    director_mode: DirectorMode = DirectorMode.STATIC,
    studio_config: StudioConfig | None = None,
    roles_dir: Path | None = None,
    role_runner: RoleRunner = run_role,
    role_timeout_seconds: int = 600,
) -> PilotCycleResult:
    state_dir.mkdir(parents=True, exist_ok=True)
    studio_config = studio_config or StudioConfig()
    roles_dir = roles_dir or repo_root / "studio" / "roles"

    director_output = _run_director(
        repo_root,
        objective=objective,
        spec=spec,
        cycle_number=cycle_number,
        state_dir=state_dir,
        director_mode=director_mode,
        studio_config=studio_config,
        roles_dir=roles_dir,
        role_runner=role_runner,
        role_timeout_seconds=role_timeout_seconds,
    )
    selected_objective = _objective_from_director_output(director_output)
    builder_output = _run_builder(
        repo_root,
        selected_objective,
        director_output,
        director_mode=director_mode,
        studio_config=studio_config,
        roles_dir=roles_dir,
        role_runner=role_runner,
        role_timeout_seconds=role_timeout_seconds,
    )
    builder_path = state_dir / f"cycle-{cycle_number:04d}-builder.md"
    builder_path.write_text(builder_output.rstrip() + "\n", encoding="utf-8")

    pilot_spec = "\n".join(
        [
            "Phase 1 pilot: no repository writes are applied by the orchestrator yet.",
            spec,
            "",
            "Builder proposal:",
            builder_output.strip(),
        ]
    )
    request = build_evaluation_request(repo_root, objective=selected_objective, spec=pilot_spec)
    request_path = state_dir / f"cycle-{cycle_number:04d}-request.json"
    report_path = state_dir / f"cycle-{cycle_number:04d}-report.json"
    proposal_lint_path = state_dir / f"cycle-{cycle_number:04d}-proposal-lint.json"
    proposal_issues = _lint_builder_proposal(repo_root, builder_output)
    proposal_lint_path.write_text(
        json.dumps(
            {
                "verdict": "REWORK" if proposal_issues else "PASS",
                "issues": proposal_issues,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    if proposal_issues:
        request_path.write_text(json.dumps(request.to_dict(), indent=2) + "\n", encoding="utf-8")
        report = EvaluationReport(
            request_branch=request.branch,
            request_commit=request.commit,
            qa=QaReport(
                verdict="REWORK",
                checks=["builder proposal lint"],
                bugs=proposal_issues,
                repro_steps=["Review the Builder proposal artifact and regenerate it with real repo paths and proposal-only wording."],
            ),
            design=DesignReport(
                verdict="BACKLOG",
                backlog_suggestions=["Keep proposal lint green before enabling repository-writing Builder cycles."],
            ),
        )
        report_path.write_text(json.dumps(report.to_dict(), indent=2) + "\n", encoding="utf-8")
        return PilotCycleResult(
            director_path=state_dir / f"cycle-{cycle_number:04d}-director.md",
            builder_path=builder_path,
            proposal_lint_path=proposal_lint_path,
            request_path=request_path,
            report_path=report_path,
            blocked=True,
            blocking_reasons=["Builder proposal lint failed.", *report.blocking_reasons()],
        )

    report = EvaluationClient(evaluation_target).evaluate(repo_root, request, state_dir, cycle_number)

    return PilotCycleResult(
        director_path=state_dir / f"cycle-{cycle_number:04d}-director.md",
        builder_path=builder_path,
        proposal_lint_path=proposal_lint_path,
        request_path=request_path,
        report_path=report_path,
        blocked=report.blocks_merge(),
        blocking_reasons=report.blocking_reasons(),
    )


def run_dry_cycle(
    repo_root: Path,
    state_dir: Path,
    *,
    objective: str = DEFAULT_OBJECTIVE,
    spec: str = DEFAULT_SPEC,
    cycle_number: int = 1,
    evaluation_target: EvaluationTarget = EvaluationTarget.LOCAL,
    director_mode: DirectorMode = DirectorMode.STATIC,
    studio_config: StudioConfig | None = None,
    roles_dir: Path | None = None,
    role_runner: RoleRunner = run_role,
    role_timeout_seconds: int = 600,
) -> DryCycleResult:
    state_dir.mkdir(parents=True, exist_ok=True)
    studio_config = studio_config or StudioConfig()
    roles_dir = roles_dir or repo_root / "studio" / "roles"
    if director_mode == DirectorMode.MODEL:
        director_output = _run_director(
            repo_root,
            objective=objective,
            spec=spec,
            cycle_number=cycle_number,
            state_dir=state_dir,
            director_mode=director_mode,
            studio_config=studio_config,
            roles_dir=roles_dir,
            role_runner=role_runner,
            role_timeout_seconds=role_timeout_seconds,
        )
        objective = _objective_from_director_output(director_output)

    request = build_evaluation_request(repo_root, objective=objective, spec=spec)
    request_path = state_dir / f"cycle-{cycle_number:04d}-request.json"
    report_path = state_dir / f"cycle-{cycle_number:04d}-report.json"
    report = EvaluationClient(evaluation_target).evaluate(repo_root, request, state_dir, cycle_number)

    return DryCycleResult(
        request_path=request_path,
        report_path=report_path,
        blocked=report.blocks_merge(),
        blocking_reasons=report.blocking_reasons(),
    )


def next_cycle_number(state_dir: Path) -> int:
    numbers: set[int] = set()
    if state_dir.is_dir():
        for path in state_dir.glob("cycle-*-director.md"):
            match = re.match(r"cycle-(\d+)-director\.md$", path.name)
            if match:
                numbers.add(int(match.group(1)))
    return (max(numbers) + 1) if numbers else 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the ai_roguelike sparky1 studio orchestrator.")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--state-dir", type=Path, default=None)
    parser.add_argument("--time", default="30m", help="Wall-clock budget for future autonomous loops.")
    parser.add_argument("--max-cycles", type=int, default=1)
    parser.add_argument("--deploy", default="false")
    parser.add_argument("--models", default="")
    parser.add_argument("--evaluation-target", choices=[target.value for target in EvaluationTarget], default=EvaluationTarget.LOCAL.value)
    parser.add_argument("--director-mode", choices=[mode.value for mode in DirectorMode], default=DirectorMode.STATIC.value)
    parser.add_argument("--role-timeout-seconds", type=int, default=600)
    parser.add_argument("--dry-run", action="store_true", help="Run one safe local evaluation cycle.")
    args = parser.parse_args(argv)

    studio_config = StudioConfig.from_model_string(args.models)
    state_dir = args.state_dir or args.repo_root / "studio" / "state"
    evaluation_target = EvaluationTarget(args.evaluation_target)
    director_mode = DirectorMode(args.director_mode)

    cycles = max(1, args.max_cycles)
    start_cycle = next_cycle_number(state_dir)
    last_blocked = False
    for offset in range(cycles):
        cycle_number = start_cycle + offset
        if (state_dir / "STOP").exists():
            print(f"STOP file found at {state_dir / 'STOP'}; exiting before cycle {cycle_number}.")
            break
        if args.dry_run:
            dry_result = run_dry_cycle(
                args.repo_root,
                state_dir,
                cycle_number=cycle_number,
                evaluation_target=evaluation_target,
                director_mode=director_mode,
                studio_config=studio_config,
                role_timeout_seconds=args.role_timeout_seconds,
            )
            last_blocked = dry_result.blocked
            print(f"cycle {cycle_number}: report={dry_result.report_path} blocked={dry_result.blocked}")
            _publish_devlog(args.repo_root, state_dir)
            continue

        pilot_result = run_pilot_cycle(
            args.repo_root,
            state_dir,
            cycle_number=cycle_number,
            evaluation_target=evaluation_target,
            director_mode=director_mode,
            studio_config=studio_config,
            role_timeout_seconds=args.role_timeout_seconds,
        )
        last_blocked = pilot_result.blocked
        print(
            f"cycle {cycle_number}: director={pilot_result.director_path} "
            f"builder={pilot_result.builder_path} report={pilot_result.report_path} blocked={pilot_result.blocked}"
        )
        _publish_devlog(args.repo_root, state_dir)

    return 1 if last_blocked else 0


def _publish_devlog(repo_root: Path, state_dir: Path) -> None:
    out_dir = repo_root / "site"
    result = publish_site(repo_root, state_dir, out_dir)
    print(f"published devlog: {result.devlog_index} ({result.cycle_count} cycles)")


def _git_output(repo_root: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", *args],
        cwd=repo_root,
        text=True,
        stderr=subprocess.DEVNULL,
    ).strip()


def _director_context(repo_root: Path, *, objective: str, spec: str) -> str:
    branch = _git_output(repo_root, "rev-parse", "--abbrev-ref", "HEAD")
    commit = _git_output(repo_root, "rev-parse", "--short", "HEAD")
    return "\n".join(
        [
            f"Branch: {branch}",
            f"Commit: {commit}",
            f"Current safe objective: {objective}",
            f"Current safe spec: {spec}",
            "Mode: no-write dry-run. Propose the next small objective only; do not request code changes yet.",
        ]
    )


def _run_director(
    repo_root: Path,
    *,
    objective: str,
    spec: str,
    cycle_number: int,
    state_dir: Path,
    director_mode: DirectorMode,
    studio_config: StudioConfig,
    roles_dir: Path,
    role_runner: RoleRunner,
    role_timeout_seconds: int,
) -> str:
    if director_mode == DirectorMode.STATIC:
        director_output = f"Objective: {objective}\nReason: {spec}"
    else:
        director_output = role_runner(
            studio_config,
            roles_dir,
            "director",
            _director_context(repo_root, objective=objective, spec=spec),
            timeout_seconds=role_timeout_seconds,
        )
    (state_dir / f"cycle-{cycle_number:04d}-director.md").write_text(director_output.rstrip() + "\n", encoding="utf-8")
    return director_output


def _builder_context(repo_root: Path, objective: str, director_output: str) -> str:
    file_summary = "\n".join(f"- {path}" for path in _known_repo_files(repo_root))
    command_summary = "\n".join(f"- {command}" for command in _known_test_commands(repo_root))
    return "\n".join(
        [
            f"Selected objective: {objective}",
            "",
            "Director output:",
            director_output.strip(),
            "",
            "Mode: Phase 1 pilot. Return an implementation proposal only; do not claim files were changed.",
            "Do not invent paths. Proposed changed files must be listed below, or explicitly labeled as NEW.",
            "Do not claim tests were run. You may recommend test commands to run later.",
            "",
            "Known existing paths:",
            file_summary,
            "",
            "Known test commands:",
            command_summary,
        ]
    )


def _run_builder(
    repo_root: Path,
    objective: str,
    director_output: str,
    *,
    director_mode: DirectorMode,
    studio_config: StudioConfig,
    roles_dir: Path,
    role_runner: RoleRunner,
    role_timeout_seconds: int,
) -> str:
    if director_mode == DirectorMode.STATIC:
        return "\n".join(
            [
                "Implementation summary: no-write static pilot proposal.",
                "Changed files: none.",
                "Tests: delegated to evaluation client.",
                f"Objective considered: {objective}",
            ]
        )
    return role_runner(
        studio_config,
        roles_dir,
        "builder",
        _builder_context(repo_root, objective, director_output),
        timeout_seconds=role_timeout_seconds,
    )


def _known_repo_files(repo_root: Path) -> list[str]:
    patterns = [
        "game/src/**/*.ts",
        "game/tests/**/*.ts",
        "game/smoke/**/*.ts",
        "eval_lab/**/*.py",
        "studio/**/*.py",
        "studio/roles/*.md",
        "*.md",
        "*.ps1",
    ]
    paths: set[str] = set()
    for pattern in patterns:
        for path in repo_root.glob(pattern):
            if path.is_file() and "studio/state" not in path.as_posix():
                paths.add(path.relative_to(repo_root).as_posix())
    return sorted(paths)


def _lint_builder_proposal(repo_root: Path, builder_output: str) -> list[str]:
    issues: list[str] = []
    seen_issues: set[str] = set()
    npm_scripts = _known_npm_scripts(repo_root)
    for line in builder_output.splitlines():
        normalized = line.strip()
        lower = normalized.lower()
        if "test commands run" in lower or "tests run" in lower:
            if "not run" not in lower and "to run later" not in lower:
                _append_issue(issues, seen_issues, "Builder proposal claims tests were run in proposal-only mode.")
        command = _extract_shell_command(normalized)
        if command:
            for issue in _lint_shell_command(command, npm_scripts):
                _append_issue(issues, seen_issues, issue)
        for proposed_path in re.findall(r"`([^`]+)`", normalized):
            proposed_path = proposed_path.strip("`").strip()
            if _is_shell_command(proposed_path):
                for issue in _lint_shell_command(proposed_path, npm_scripts):
                    _append_issue(issues, seen_issues, issue)
                continue
            if not _looks_like_repo_path(proposed_path):
                continue
            if "new" in lower:
                continue
            if not (repo_root / proposed_path).is_file():
                _append_issue(issues, seen_issues, f"Builder proposal references a non-existent path: {proposed_path}")
    return issues


def _append_issue(issues: list[str], seen_issues: set[str], issue: str) -> None:
    if issue not in seen_issues:
        seen_issues.add(issue)
        issues.append(issue)


def _extract_shell_command(line: str) -> str | None:
    stripped = line.strip()
    if not stripped or stripped.startswith(("#", "```")):
        return None
    stripped = stripped.lstrip("-*").strip()
    stripped = stripped.strip("`").strip()
    if _is_shell_command(stripped):
        return _normalize_shell_command(stripped)
    return None


def _normalize_shell_command(command: str) -> str:
    return " ".join(part.strip("`") for part in command.strip().strip("`").split())


def _is_shell_command(value: str) -> bool:
    return value.strip("`").startswith(("npm ", "npx ", "python ", "python3 ", "playwright ", "vitest ", "tsc "))


def _lint_shell_command(command: str, npm_scripts: set[str]) -> list[str]:
    tokens = _normalize_shell_command(command).split()
    if not tokens:
        return []
    executable = tokens[0]
    if executable == "npm":
        return _lint_npm_command(tokens, npm_scripts)
    if executable == "npx":
        return _lint_npx_command(tokens)
    if executable in {"playwright", "vitest", "tsc"}:
        return []
    if executable in {"python", "python3"}:
        if tokens[:3] == [executable, "-m", "unittest"]:
            return []
        return [f"Unsupported Python command: {' '.join(tokens[:3])}"]
    return []


def _lint_npm_command(tokens: list[str], npm_scripts: set[str]) -> list[str]:
    if len(tokens) < 2:
        return ["Incomplete npm command in Builder proposal."]
    command = tokens[1]
    if command == "run":
        if len(tokens) < 3:
            return ["Incomplete npm run command in Builder proposal."]
        script = tokens[2]
        if script not in npm_scripts:
            return [f"Unknown npm script in Builder proposal: {script}"]
        return []
    if command == "test":
        if "test" not in npm_scripts:
            return ["Builder proposal recommends npm test, but game/package.json has no test script."]
        return []
    if command in {"ci", "install"}:
        return []
    return [f"Unsupported npm command: npm {command}"]


def _lint_npx_command(tokens: list[str]) -> list[str]:
    if len(tokens) < 2:
        return ["Incomplete npx command in Builder proposal."]
    tool = tokens[1]
    if tool in {"playwright", "vitest", "tsc"}:
        return []
    return [f"Unsupported npx command: npx {tool}"]


def _known_npm_scripts(repo_root: Path) -> set[str]:
    package_json = repo_root / "game" / "package.json"
    if not package_json.is_file():
        return set()
    data = json.loads(package_json.read_text(encoding="utf-8"))
    scripts = data.get("scripts", {})
    if not isinstance(scripts, dict):
        return set()
    return {str(name) for name in scripts}


def _known_test_commands(repo_root: Path) -> list[str]:
    scripts = _known_npm_scripts(repo_root)
    commands: list[str] = []
    if "test" in scripts:
        commands.append("npm test")
    for script in ("typecheck", "build", "smoke"):
        if script in scripts:
            commands.append(f"npm run {script}")
    commands.extend(["python -m unittest discover -s studio/tests", "python -m unittest discover -s eval_lab/tests"])
    return commands


def _looks_like_repo_path(value: str) -> bool:
    if value.startswith(("http://", "https://")):
        return False
    if any(character.isspace() for character in value):
        return False
    return "/" in value or "\\" in value


def _objective_from_director_output(output: str) -> str:
    for line in output.splitlines():
        normalized = line.strip().lstrip("-*").strip()
        if not normalized:
            continue
        for prefix in ("Objective:", "Next objective:", "OBJECTIVE:"):
            if normalized.startswith(prefix):
                normalized = normalized[len(prefix) :].strip()
                break
        return normalized
    return DEFAULT_OBJECTIVE


if __name__ == "__main__":
    sys.exit(main())
