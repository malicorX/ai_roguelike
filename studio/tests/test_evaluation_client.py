import json
import tempfile
import unittest
from pathlib import Path

from eval_lab.protocol import EvaluationRequest
from studio.evaluation_client import EvaluationClient, EvaluationTarget


class EvaluationClientTest(unittest.TestCase):
    def test_local_target_runs_in_process_and_writes_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            game = repo / "game"
            game.mkdir()
            self._write_success_npm(game)
            request = EvaluationRequest(
                branch="main",
                commit="abc1234",
                objective="Verify",
                spec="Run checks",
            )

            report = EvaluationClient(EvaluationTarget.LOCAL).evaluate(repo, request, repo / "state", 1)

        self.assertEqual(report.qa.verdict, "PASS")
        self.assertEqual(report.request_commit, "abc1234")

    def test_sparky2_target_uses_remote_checkout_and_fetches_report(self) -> None:
        commands: list[list[str]] = []

        def fake_run(command: list[str]) -> None:
            commands.append(command)
            if command[0] == "scp" and command[1].endswith("cycle-0002-report.json"):
                local_report = Path(command[2])
                local_report.write_text(
                    json.dumps(
                        {
                            "request_branch": "main",
                            "request_commit": "abc1234",
                            "qa": {"verdict": "PASS", "checks": [], "bugs": [], "repro_steps": []},
                            "design": {
                                "verdict": "BACKLOG",
                                "fun_notes": [],
                                "balance_notes": [],
                                "visual_notes": ["ok"],
                                "backlog_suggestions": [],
                            },
                        }
                    ),
                    encoding="utf-8",
                )

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            state_dir = repo / "state"
            request = EvaluationRequest(branch="main", commit="abc1234", objective="Verify", spec="Run checks")

            report = EvaluationClient(EvaluationTarget.SPARKY2, run_command=fake_run).evaluate(repo, request, state_dir, 2)

        self.assertEqual(report.design.visual_notes, ["ok"])
        self.assertEqual(commands[0][:2], ["ssh", "sparky2"])
        self.assertEqual(commands[1][0], "scp")
        self.assertIn("eval_lab/reports/cycle-0002-report.json", commands[2][2])
        self.assertEqual(commands[3][0], "scp")

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
