import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from studio.evaluation_client import EvaluationTarget
from studio.config import StudioConfig
from studio.orchestrator import DirectorMode, build_evaluation_request, run_dry_cycle


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
