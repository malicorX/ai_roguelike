import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from studio.evaluation_client import EvaluationTarget
from studio.config import StudioConfig
from studio.orchestrator import DirectorMode, build_evaluation_request, main, next_cycle_number, run_dry_cycle, run_pilot_cycle


class OrchestratorTest(unittest.TestCase):
    def test_build_evaluation_request_uses_git_identity(self) -> None:
        with patch("studio.orchestrator._git_output") as git_output:
            git_output.side_effect = ["feature/test", "abc1234"]

            request = build_evaluation_request(
                Path("/repo"),
                objective="Keep the v0 game playable",
                spec="Run the current deterministic gates.",
                changed_files=["game/src/main.ts"],
            )

        self.assertEqual(request.branch, "feature/test")
        self.assertEqual(request.commit, "abc1234")
        self.assertEqual(request.seeds, [1, 7, 42])
        self.assertEqual(request.focus, ["qa", "browser-smoke", "visual-readability"])

    def test_dry_cycle_writes_request_and_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            state_dir = repo / "studio" / "state"
            game = repo / "game"
            game.mkdir(parents=True)
            self._write_success_npm(game)

            with patch("studio.orchestrator._git_output") as git_output:
                git_output.side_effect = ["main", "abc1234"]
                result = run_dry_cycle(
                    repo,
                    state_dir,
                    objective="Verify current build",
                    spec="Run deterministic local gates.",
                    cycle_number=1,
                    evaluation_target=EvaluationTarget.LOCAL,
                )

            request_data = json.loads(result.request_path.read_text(encoding="utf-8"))
            report_data = json.loads(result.report_path.read_text(encoding="utf-8"))

        self.assertFalse(result.blocked)
        self.assertEqual(request_data["branch"], "main")
        self.assertEqual(report_data["qa"]["verdict"], "PASS")

    def test_dry_cycle_can_use_director_model_output_as_objective(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            state_dir = repo / "studio" / "state"
            roles_dir = repo / "studio" / "roles"
            game = repo / "game"
            game.mkdir(parents=True)
            roles_dir.mkdir(parents=True)
            self._write_success_npm(game)

            with patch("studio.orchestrator._git_output") as git_output:
                git_output.side_effect = ["main", "abc1234", "main", "abc1234"]
                result = run_dry_cycle(
                    repo,
                    state_dir,
                    cycle_number=2,
                    evaluation_target=EvaluationTarget.LOCAL,
                    director_mode=DirectorMode.MODEL,
                    studio_config=StudioConfig.from_model_string("director=test-model"),
                    roles_dir=roles_dir,
                    role_runner=lambda *_args, **_kwargs: "Improve visual clarity.\nReason: current v0 needs stronger readability.",
                )

            request_data = json.loads(result.request_path.read_text(encoding="utf-8"))
            director_output = (state_dir / "cycle-0002-director.md").read_text(encoding="utf-8")

        self.assertFalse(result.blocked)
        self.assertEqual(request_data["objective"], "Improve visual clarity.")
        self.assertIn("Reason: current v0 needs stronger readability.", director_output)

    def test_pilot_cycle_records_director_and_builder_artifacts_before_evaluation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            state_dir = repo / "studio" / "state"
            roles_dir = repo / "studio" / "roles"
            game = repo / "game"
            src = game / "src"
            game.mkdir(parents=True)
            src.mkdir()
            (game / "package.json").write_text(
                json.dumps({"scripts": {"test": "vitest run", "smoke": "npm run build && playwright test"}}),
                encoding="utf-8",
            )
            (src / "main.ts").write_text("export {};\n", encoding="utf-8")
            roles_dir.mkdir(parents=True)
            self._write_success_npm(game)
            builder_contexts: list[str] = []

            def fake_role_runner(*args: object, **_kwargs: object) -> str:
                role = args[2]
                if role == "director":
                    return "Objective: Add a visible restart affordance.\nReason: death recovery should be obvious."
                if role == "builder":
                    builder_contexts.append(str(args[3]))
                    return "Implementation summary: no-write pilot proposal.\nChanged files: none.\nTests: not run by builder."
                raise AssertionError(f"Unexpected role: {role}")

            with patch("studio.orchestrator._git_output") as git_output:
                git_output.side_effect = ["main", "abc1234", "main", "abc1234"]
                result = run_pilot_cycle(
                    repo,
                    state_dir,
                    cycle_number=3,
                    evaluation_target=EvaluationTarget.LOCAL,
                    director_mode=DirectorMode.MODEL,
                    studio_config=StudioConfig.from_model_string("director=test-model,builder=test-model"),
                    roles_dir=roles_dir,
                    role_runner=fake_role_runner,
                )

            request_data = json.loads(result.request_path.read_text(encoding="utf-8"))
            director_output = result.director_path.read_text(encoding="utf-8")
            builder_output = result.builder_path.read_text(encoding="utf-8")

        self.assertFalse(result.blocked)
        self.assertEqual(request_data["objective"], "Add a visible restart affordance.")
        self.assertIn("death recovery should be obvious", director_output)
        self.assertIn("no-write pilot proposal", builder_output)
        self.assertIn("Phase 1 pilot", request_data["spec"])
        self.assertIn("game/src/main.ts", builder_contexts[0])
        self.assertIn("Do not invent paths", builder_contexts[0])
        self.assertIn("Do not claim tests were run", builder_contexts[0])
        self.assertIn("npm test", builder_contexts[0])
        self.assertIn("npm run smoke", builder_contexts[0])

    def test_pilot_cycle_blocks_invalid_builder_proposal_before_evaluation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            state_dir = repo / "studio" / "state"
            roles_dir = repo / "studio" / "roles"
            game = repo / "game"
            game.mkdir(parents=True)
            roles_dir.mkdir(parents=True)
            self._write_success_npm(game)

            def fake_role_runner(*args: object, **_kwargs: object) -> str:
                role = args[2]
                if role == "director":
                    return "Objective: Improve movement observability."
                if role == "builder":
                    return "\n".join(
                        [
                            "Implementation summary: add movement logs.",
                            "Proposed changed files:",
                            "- `src/controllers/PlayerMovementController.js`",
                            "Test Commands Run:",
                            "npm test",
                        ]
                    )
                raise AssertionError(f"Unexpected role: {role}")

            with patch("studio.orchestrator._git_output") as git_output, patch("studio.orchestrator.EvaluationClient") as evaluation_client:
                git_output.side_effect = ["main", "abc1234", "main", "abc1234"]
                result = run_pilot_cycle(
                    repo,
                    state_dir,
                    cycle_number=5,
                    evaluation_target=EvaluationTarget.LOCAL,
                    director_mode=DirectorMode.MODEL,
                    studio_config=StudioConfig.from_model_string("director=test-model,builder=test-model"),
                    roles_dir=roles_dir,
                    role_runner=fake_role_runner,
                )

            lint_data = json.loads(result.proposal_lint_path.read_text(encoding="utf-8"))
            report_data = json.loads(result.report_path.read_text(encoding="utf-8"))

        self.assertTrue(result.blocked)
        self.assertIn("Builder proposal lint failed.", result.blocking_reasons)
        self.assertGreaterEqual(len(lint_data["issues"]), 2)
        self.assertEqual(report_data["qa"]["verdict"], "REWORK")
        evaluation_client.assert_not_called()

    def test_pilot_cycle_allows_backticked_test_commands_with_real_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            state_dir = repo / "studio" / "state"
            roles_dir = repo / "studio" / "roles"
            game = repo / "game"
            tests = game / "tests"
            src = game / "src"
            tests.mkdir(parents=True)
            src.mkdir()
            (game / "package.json").write_text(json.dumps({"scripts": {"test": "vitest run"}}), encoding="utf-8")
            (tests / "engine.test.ts").write_text("export {};\n", encoding="utf-8")
            (src / "engine.ts").write_text("export {};\n", encoding="utf-8")
            roles_dir.mkdir(parents=True)
            self._write_success_npm(game)

            def fake_role_runner(*args: object, **_kwargs: object) -> str:
                role = args[2]
                if role == "director":
                    return "Objective: Add movement observability."
                if role == "builder":
                    return "\n".join(
                        [
                            "Implementation summary: add debug logging.",
                            "Proposed changed files:",
                            "- `game/src/engine.ts`",
                            "Recommended Test Commands:",
                            "- `npm test -- game/tests/engine.test.ts`",
                        ]
                    )
                raise AssertionError(f"Unexpected role: {role}")

            with patch("studio.orchestrator._git_output") as git_output:
                git_output.side_effect = ["main", "abc1234", "main", "abc1234"]
                result = run_pilot_cycle(
                    repo,
                    state_dir,
                    cycle_number=6,
                    evaluation_target=EvaluationTarget.LOCAL,
                    director_mode=DirectorMode.MODEL,
                    studio_config=StudioConfig.from_model_string("director=test-model,builder=test-model"),
                    roles_dir=roles_dir,
                    role_runner=fake_role_runner,
                )

            lint_data = json.loads(result.proposal_lint_path.read_text(encoding="utf-8"))

        self.assertFalse(result.blocked)
        self.assertEqual(lint_data["verdict"], "PASS")

    def test_pilot_cycle_allows_markdown_list_backticked_npm_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            state_dir = repo / "studio" / "state"
            roles_dir = repo / "studio" / "roles"
            game = repo / "game"
            smoke = game / "smoke"
            src = game / "src"
            smoke.mkdir(parents=True)
            src.mkdir()
            (game / "package.json").write_text(
                json.dumps({"scripts": {"test": "vitest run", "smoke": "playwright test"}}),
                encoding="utf-8",
            )
            (src / "render.ts").write_text("export {};\n", encoding="utf-8")
            (smoke / "playability.spec.ts").write_text("export {};\n", encoding="utf-8")
            roles_dir.mkdir(parents=True)
            self._write_success_npm(game)

            def fake_role_runner(*args: object, **_kwargs: object) -> str:
                role = args[2]
                if role == "director":
                    return "Objective: Improve smoke failure logging."
                if role == "builder":
                    return "\n".join(
                        [
                            "Implementation summary: add smoke failure logs.",
                            "Proposed changed files:",
                            "- `game/smoke/playability.spec.ts`",
                            "Recommended Test Commands:",
                            "- `npm run smoke`",
                            "- `npm test`",
                        ]
                    )
                raise AssertionError(f"Unexpected role: {role}")

            with patch("studio.orchestrator._git_output") as git_output:
                git_output.side_effect = ["main", "abc1234", "main", "abc1234"]
                result = run_pilot_cycle(
                    repo,
                    state_dir,
                    cycle_number=8,
                    evaluation_target=EvaluationTarget.LOCAL,
                    director_mode=DirectorMode.MODEL,
                    studio_config=StudioConfig.from_model_string("director=test-model,builder=test-model"),
                    roles_dir=roles_dir,
                    role_runner=fake_role_runner,
                )

            lint_data = json.loads(result.proposal_lint_path.read_text(encoding="utf-8"))

        self.assertFalse(result.blocked)
        self.assertEqual(lint_data["verdict"], "PASS")
        self.assertEqual(lint_data["issues"], [])

    def test_pilot_cycle_allows_directory_mentions_in_builder_prose(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            state_dir = repo / "studio" / "state"
            roles_dir = repo / "studio" / "roles"
            game = repo / "game"
            smoke = game / "smoke"
            smoke.mkdir(parents=True)
            (game / "package.json").write_text(json.dumps({"scripts": {"test": "vitest run", "smoke": "playwright test"}}), encoding="utf-8")
            roles_dir.mkdir(parents=True)
            self._write_success_npm(game)

            def fake_role_runner(*args: object, **_kwargs: object) -> str:
                role = args[2]
                if role == "director":
                    return "Objective: Add canvas render smoke."
                if role == "builder":
                    return "\n".join(
                        [
                            "Implementation summary: add smoke spec.",
                            "Mention directory `game/smoke/` in prose.",
                            "Proposed changed files:",
                            "- `game/smoke/canvas-render.spec.ts` NEW",
                            "Recommended Test Commands:",
                            "- `npm run smoke`",
                        ]
                    )
                raise AssertionError(f"Unexpected role: {role}")

            with patch("studio.orchestrator._git_output") as git_output:
                git_output.side_effect = ["main", "abc1234", "main", "abc1234"]
                result = run_pilot_cycle(
                    repo,
                    state_dir,
                    cycle_number=11,
                    evaluation_target=EvaluationTarget.LOCAL,
                    director_mode=DirectorMode.MODEL,
                    studio_config=StudioConfig.from_model_string("director=test-model,builder=test-model"),
                    roles_dir=roles_dir,
                    role_runner=fake_role_runner,
                )

            lint_data = json.loads(result.proposal_lint_path.read_text(encoding="utf-8"))

        self.assertFalse(result.blocked)
        self.assertEqual(lint_data["verdict"], "PASS")

    def test_pilot_cycle_blocks_unknown_test_commands_before_evaluation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            state_dir = repo / "studio" / "state"
            roles_dir = repo / "studio" / "roles"
            game = repo / "game"
            src = game / "src"
            src.mkdir(parents=True)
            (src / "render.ts").write_text("export {};\n", encoding="utf-8")
            (game / "package.json").write_text(json.dumps({"scripts": {"test": "vitest run", "smoke": "playwright test"}}), encoding="utf-8")
            roles_dir.mkdir(parents=True)
            self._write_success_npm(game)

            def fake_role_runner(*args: object, **_kwargs: object) -> str:
                role = args[2]
                if role == "director":
                    return "Objective: Add debug overlay proposal."
                if role == "builder":
                    return "\n".join(
                        [
                            "Implementation summary: add debug overlay.",
                            "Proposed changed files:",
                            "- `game/src/render.ts`",
                            "Recommended Test Commands:",
                            "npx jest game/tests/render.test.ts",
                            "npm run test:smoke --game/smoke/visual-readability.spec.ts",
                        ]
                    )
                raise AssertionError(f"Unexpected role: {role}")

            with patch("studio.orchestrator._git_output") as git_output, patch("studio.orchestrator.EvaluationClient") as evaluation_client:
                git_output.side_effect = ["main", "abc1234", "main", "abc1234"]
                result = run_pilot_cycle(
                    repo,
                    state_dir,
                    cycle_number=7,
                    evaluation_target=EvaluationTarget.LOCAL,
                    director_mode=DirectorMode.MODEL,
                    studio_config=StudioConfig.from_model_string("director=test-model,builder=test-model"),
                    roles_dir=roles_dir,
                    role_runner=fake_role_runner,
                )

            lint_data = json.loads(result.proposal_lint_path.read_text(encoding="utf-8"))

        self.assertTrue(result.blocked)
        self.assertIn("Builder proposal lint failed.", result.blocking_reasons)
        self.assertIn("Unsupported npx command: npx jest", lint_data["issues"])
        self.assertIn("Unknown npm script in Builder proposal: test:smoke", lint_data["issues"])
        evaluation_client.assert_not_called()

    def test_static_pilot_cycle_does_not_call_role_runner(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            state_dir = repo / "studio" / "state"
            game = repo / "game"
            game.mkdir(parents=True)
            self._write_success_npm(game)

            with patch("studio.orchestrator._git_output") as git_output:
                git_output.side_effect = ["main", "abc1234"]
                result = run_pilot_cycle(
                    repo,
                    state_dir,
                    cycle_number=4,
                    evaluation_target=EvaluationTarget.LOCAL,
                    director_mode=DirectorMode.STATIC,
                    role_runner=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("role runner should not be called")),
                )

            request_data = json.loads(result.request_path.read_text(encoding="utf-8"))
            builder_output = result.builder_path.read_text(encoding="utf-8")

        self.assertFalse(result.blocked)
        self.assertEqual(request_data["objective"], "Verify that the current v0 game remains playable.")
        self.assertIn("no-write static pilot", builder_output)

    def test_main_runs_pilot_loop_when_not_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            state_dir = repo / "studio" / "state"

            with patch("studio.orchestrator.run_pilot_cycle") as pilot_cycle:
                pilot_cycle.return_value.blocked = False
                pilot_cycle.return_value.report_path = state_dir / "cycle-0001-report.json"
                exit_code = main(
                    [
                        "--repo-root",
                        str(repo),
                        "--state-dir",
                        str(state_dir),
                        "--max-cycles",
                        "1",
                        "--evaluation-target",
                        "local",
                    ]
                )

        self.assertEqual(exit_code, 0)
        pilot_cycle.assert_called_once()

    def test_main_skips_pilot_loop_when_stop_file_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            state_dir = repo / "studio" / "state"
            state_dir.mkdir(parents=True)
            (state_dir / "STOP").write_text("stop\n", encoding="utf-8")

            with patch("studio.orchestrator.run_pilot_cycle") as pilot_cycle:
                exit_code = main(
                    [
                        "--repo-root",
                        str(repo),
                        "--state-dir",
                        str(state_dir),
                        "--max-cycles",
                        "1",
                        "--evaluation-target",
                        "local",
                    ]
                )

        self.assertEqual(exit_code, 0)
        pilot_cycle.assert_not_called()

    def test_next_cycle_number_starts_after_latest_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir)
            (state_dir / "cycle-0003-director.md").write_text("Objective: test\n", encoding="utf-8")

            self.assertEqual(next_cycle_number(state_dir), 4)

    def test_main_continues_cycle_number_from_existing_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            state_dir = repo / "studio" / "state"
            state_dir.mkdir(parents=True)
            (state_dir / "cycle-0002-director.md").write_text("Objective: test\n", encoding="utf-8")

            with patch("studio.orchestrator.run_pilot_cycle") as pilot_cycle:
                pilot_cycle.return_value.blocked = False
                pilot_cycle.return_value.report_path = state_dir / "cycle-0003-report.json"
                exit_code = main(
                    [
                        "--repo-root",
                        str(repo),
                        "--state-dir",
                        str(state_dir),
                        "--max-cycles",
                        "1",
                        "--evaluation-target",
                        "local",
                    ]
                )

        self.assertEqual(exit_code, 0)
        pilot_cycle.assert_called_once()
        self.assertEqual(pilot_cycle.call_args.kwargs["cycle_number"], 3)

    def test_write_cycle_blocks_when_builder_output_has_no_diff(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            state_dir = repo / "studio" / "state"
            roles_dir = repo / "studio" / "roles"
            game = repo / "game"
            src = game / "src"
            src.mkdir(parents=True)
            (game / "package.json").write_text(json.dumps({"scripts": {"test": "vitest run"}}), encoding="utf-8")
            (src / "render.ts").write_text("export {};\n", encoding="utf-8")
            roles_dir.mkdir(parents=True)
            self._init_git_repo(repo)
            self._write_success_npm(game)

            def fake_role_runner(*args: object, **_kwargs: object) -> str:
                role = args[2]
                if role == "director":
                    return "Objective: Add HUD turn counter."
                if role == "builder":
                    return "Implementation summary: forgot the diff."
                raise AssertionError(f"Unexpected role: {role}")

            with patch("studio.orchestrator._git_output") as git_output:
                git_output.side_effect = ["main", "abc1234", "main", "abc1234"]
                result = run_pilot_cycle(
                    repo,
                    state_dir,
                    cycle_number=9,
                    evaluation_target=EvaluationTarget.LOCAL,
                    director_mode=DirectorMode.MODEL,
                    studio_config=StudioConfig.from_model_string("director=test-model,builder=test-model"),
                    roles_dir=roles_dir,
                    role_runner=fake_role_runner,
                    apply_writes=True,
                )

            report_data = json.loads(result.report_path.read_text(encoding="utf-8"))

        self.assertTrue(result.blocked)
        self.assertIn("Write cycle blocked before evaluation.", result.blocking_reasons)
        self.assertEqual(report_data["qa"]["verdict"], "REWORK")

    def test_write_cycle_applies_diff_merges_on_green_evaluation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            state_dir = repo / "studio" / "state"
            roles_dir = repo / "studio" / "roles"
            game = repo / "game"
            src = game / "src"
            src.mkdir(parents=True)
            (game / "package.json").write_text(json.dumps({"scripts": {"test": "vitest run"}}), encoding="utf-8")
            (src / "render.ts").write_text("export const label = 'play';\n", encoding="utf-8")
            roles_dir.mkdir(parents=True)
            self._init_git_repo(repo)
            self._write_success_npm(game)

            builder_output = "\n".join(
                [
                    "Implementation summary: update render label.",
                    "Proposed changed files:",
                    "- `game/src/render.ts`",
                    "```diff",
                    "diff --git a/game/src/render.ts b/game/src/render.ts",
                    "--- a/game/src/render.ts",
                    "+++ b/game/src/render.ts",
                    "@@ -1 +1 @@",
                    "-export const label = 'play';",
                    "+export const label = 'play-updated';",
                    "```",
                ]
            )

            def fake_role_runner(*args: object, **_kwargs: object) -> str:
                role = args[2]
                if role == "director":
                    return "Objective: Update render label."
                if role == "builder":
                    return builder_output
                raise AssertionError(f"Unexpected role: {role}")

            with patch("studio.orchestrator._git_output") as git_output, patch("studio.orchestrator.push_main"), patch(
                "studio.orchestrator.EvaluationClient"
            ) as evaluation_client:
                git_output.side_effect = ["main", "abc1234", "main", "abc1234"]
                evaluation_client.return_value.evaluate.return_value.blocks_merge.return_value = False
                evaluation_client.return_value.evaluate.return_value.blocking_reasons.return_value = []
                result = run_pilot_cycle(
                    repo,
                    state_dir,
                    cycle_number=10,
                    evaluation_target=EvaluationTarget.LOCAL,
                    director_mode=DirectorMode.MODEL,
                    studio_config=StudioConfig.from_model_string("director=test-model,builder=test-model"),
                    roles_dir=roles_dir,
                    role_runner=fake_role_runner,
                    apply_writes=True,
                )

            apply_data = json.loads(result.apply_path.read_text(encoding="utf-8"))
            merge_data = json.loads(result.merge_path.read_text(encoding="utf-8"))
            render_source = (src / "render.ts").read_text(encoding="utf-8")

        self.assertFalse(result.blocked)
        self.assertEqual(apply_data["verdict"], "APPLIED")
        self.assertEqual(merge_data["verdict"], "MERGED")
        self.assertIn("play-updated", render_source)

    def _init_git_repo(self, repo: Path) -> None:
        import subprocess

        subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "test"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "branch", "-M", "main"], cwd=repo, check=True, capture_output=True)

    def _write_success_npm(self, game: Path) -> None:
        script = game / ("npm.cmd" if _is_windows() else "npm")
        if _is_windows():
            script.write_text("@echo off\r\nexit /b 0\r\n", encoding="utf-8")
        else:
            script.write_text("#!/usr/bin/env sh\nexit 0\n", encoding="utf-8")
            script.chmod(0o755)


def _is_windows() -> bool:
    return __import__("os").name == "nt"


if __name__ == "__main__":
    unittest.main()
