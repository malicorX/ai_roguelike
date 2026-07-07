import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from studio.evaluation_client import EvaluationTarget
from studio.config import StudioConfig
from studio.orchestrator import DirectorMode, build_evaluation_request, main, run_dry_cycle, run_pilot_cycle


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
