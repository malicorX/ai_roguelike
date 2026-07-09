import json
import tempfile
import unittest
from pathlib import Path

from studio.cycle_report import render_cycle_process_report, render_cycle_process_summary, save_cycle_process_report
from studio.proposals import ProposalBoard, parse_agent_proposal, parse_proposal_critique, save_proposal_board


class CycleReportTest(unittest.TestCase):
    def test_render_cycle_process_report_includes_proposals_and_critiques(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir)
            enemy = parse_agent_proposal(
                "enemy_designer",
                "Title: The Anchor\nGoal: Pull player on hit.\nAcceptance: Player moves 1 tile closer.",
                index=1,
            )
            critique = parse_proposal_critique("qa_critic", "Verdict: PASS\n- Concrete and testable.")
            board = ProposalBoard(cycle_number=12, proposals=[enemy], critiques=[critique], selected_id=enemy.id)
            save_proposal_board(state_dir, board)
            (state_dir / "cycle-0012-run.log").write_text("running proposal specialists\nrunning director\n", encoding="utf-8")
            (state_dir / "cycle-0012-director.md").write_text(
                "Proposal: enemy_designer-1\nObjective: Implement The Anchor.\n", encoding="utf-8"
            )
            (state_dir / "cycle-0012-request.json").write_text(
                json.dumps({"objective": "Implement The Anchor.", "branch": "main", "commit": "abc"}),
                encoding="utf-8",
            )
            (state_dir / "cycle-0012-report.json").write_text(
                json.dumps({"qa": {"verdict": "PASS"}, "design": {"verdict": "PASS"}}),
                encoding="utf-8",
            )

            report = render_cycle_process_report(state_dir, 12)

        self.assertIn("CYCLE 0012", report)
        self.assertIn("The Anchor", report)
        self.assertIn("qa_critic", report)
        self.assertIn("Verdict: PASS", report)
        self.assertIn("running proposal specialists", report)
        self.assertIn("devlog/cycle-0012.html", report)

    def test_render_cycle_process_summary_is_brief(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir)
            enemy = parse_agent_proposal("enemy_designer", "Title: Fog Bat\nGoal: Threat.", index=1)
            board = ProposalBoard(cycle_number=3, proposals=[enemy], critiques=[], selected_id=enemy.id)
            save_proposal_board(state_dir, board)
            (state_dir / "cycle-0003-director.md").write_text("Objective: Test.\n", encoding="utf-8")
            (state_dir / "cycle-0003-report.json").write_text('{"qa":{"verdict":"REWORK"}}', encoding="utf-8")

            summary = render_cycle_process_summary(state_dir, 3)

        self.assertIn("Cycle 0003 summary", summary)
        self.assertIn("devlog/cycle-0003.html", summary)
        self.assertNotIn("AGENT PROCESS REPORT", summary)

    def test_save_cycle_process_report_writes_markdown_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir)
            enemy = parse_agent_proposal("enemy_designer", "Title: Fog Bat\nGoal: Threat.", index=1)
            board = ProposalBoard(cycle_number=3, proposals=[enemy], critiques=[], selected_id=enemy.id)
            save_proposal_board(state_dir, board)

            path = save_cycle_process_report(state_dir, 3)

            self.assertTrue(path.is_file())
            self.assertIn("Fog Bat", path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
