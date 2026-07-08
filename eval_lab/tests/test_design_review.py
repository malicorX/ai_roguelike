import tempfile
import unittest
from pathlib import Path

from eval_lab.design_review import run_design_review
from eval_lab.protocol import EvaluationRequest


class DesignReviewTest(unittest.TestCase):
    def test_run_design_review_uses_default_report_without_models(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            request = EvaluationRequest(
                branch="main",
                commit="abc1234",
                objective="Improve HUD clarity",
                spec="Pilot spec",
            )

            report = run_design_review(repo, request, roles_dir=repo / "studio" / "roles", qa_passed=True)

        self.assertEqual(report.verdict, "BACKLOG")
        self.assertIn("Automated canvas readability", report.visual_notes[0])

    def test_run_design_review_blocks_on_art_director_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            roles_dir = repo / "studio" / "roles"
            roles_dir.mkdir(parents=True)
            (roles_dir / "art_director.md").write_text("# Art Director\n", encoding="utf-8")
            request = EvaluationRequest(
                branch="main",
                commit="abc1234",
                objective="Improve HUD clarity",
                spec="Pilot spec",
                designer_spec="Acceptance: HUD shows turn count.",
                models="art_director=test-model",
            )

            def fake_role_runner(_config, _roles_dir, role, _context, timeout_seconds=120) -> str:
                self.assertEqual(role, "art_director")
                return "BLOCK: Player sprite overlaps the status line."

            report = run_design_review(
                repo,
                request,
                roles_dir=roles_dir,
                qa_passed=True,
                role_runner=fake_role_runner,
            )

        self.assertEqual(report.verdict, "BLOCK")
        self.assertEqual(report.evaluation_roles["art_director"]["verdict"], "BLOCK")

    def test_run_design_review_merges_player_json_notes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            roles_dir = repo / "studio" / "roles"
            roles_dir.mkdir(parents=True)
            (roles_dir / "player.md").write_text("# Player\n", encoding="utf-8")
            request = EvaluationRequest(
                branch="main",
                commit="abc1234",
                objective="Improve enemy pressure",
                spec="Pilot spec",
                models="player=test-model",
            )
            player_json = (
                '{"reached":"floor 1","deaths":1,'
                '"bugs":[],"fun_notes":["Combat loop is readable"],'
                '"balance_notes":["Enemy damage feels spiky"]}'
            )

            def fake_role_runner(_config, _roles_dir, role, _context, timeout_seconds=120) -> str:
                self.assertEqual(role, "player")
                return player_json

            report = run_design_review(
                repo,
                request,
                roles_dir=roles_dir,
                qa_passed=True,
                role_runner=fake_role_runner,
            )

        self.assertIn("Combat loop is readable", report.fun_notes)
        self.assertIn("Enemy damage feels spiky", report.balance_notes)


if __name__ == "__main__":
    unittest.main()
