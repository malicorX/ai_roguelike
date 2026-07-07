import json
import tempfile
import unittest
from pathlib import Path

from eval_lab.evaluate_candidate import evaluate_candidate
from eval_lab.protocol import EvaluationRequest


class EvaluateCandidateTest(unittest.TestCase):
    def test_evaluate_candidate_reports_pass_when_checks_succeed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            game = repo / "game"
            game.mkdir()
            self._write_success_npm(game)

            request = EvaluationRequest(
                branch="cycle-1",
                commit="abc1234",
                objective="Smoke test the game",
                spec="Run the deterministic checks.",
                changed_files=["game/src/engine.ts"],
                seeds=[1],
                focus=["qa"],
            )

            report = evaluate_candidate(repo, request)

        self.assertEqual(report.request_branch, "cycle-1")
        self.assertEqual(report.request_commit, "abc1234")
        self.assertEqual(report.qa.verdict, "PASS")
        self.assertEqual(report.qa.checks, ["npm test", "npm run build", "npm run smoke"])
        self.assertEqual(report.design.verdict, "BACKLOG")
        self.assertFalse(report.blocks_merge())

    def test_evaluate_candidate_reports_rework_when_a_check_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            game = repo / "game"
            game.mkdir()
            self._write_failing_npm(game)

            request = EvaluationRequest(
                branch="cycle-2",
                commit="def5678",
                objective="Smoke test the game",
                spec="Run the deterministic checks.",
            )

            report = evaluate_candidate(repo, request)

        self.assertEqual(report.qa.verdict, "REWORK")
        self.assertTrue(report.blocks_merge())
        self.assertIn("npm test failed", report.qa.bugs)

    def _write_success_npm(self, game: Path) -> None:
        self._write_fake_npm(game, exit_code=0)

    def _write_failing_npm(self, game: Path) -> None:
        self._write_fake_npm(game, exit_code=1)

    def _write_fake_npm(self, game: Path, exit_code: int) -> None:
        script = game / ("npm.cmd" if _is_windows() else "npm")
        if _is_windows():
            script.write_text(f"@echo off\r\nexit /b {exit_code}\r\n", encoding="utf-8")
        else:
            script.write_text(f"#!/usr/bin/env sh\nexit {exit_code}\n", encoding="utf-8")
            script.chmod(0o755)
        (game / "package.json").write_text(json.dumps({"scripts": {"test": "fake"}}), encoding="utf-8")


def _is_windows() -> bool:
    return __import__("os").name == "nt"


if __name__ == "__main__":
    unittest.main()
