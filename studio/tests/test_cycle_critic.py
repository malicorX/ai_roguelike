import json
import tempfile
import unittest
from pathlib import Path

from studio.cycle_critic import run_cycle_critic, write_cycle_critic
from studio.proposals import ProposalBoard, parse_agent_proposal, save_proposal_board


class CycleCriticTest(unittest.TestCase):
    def test_run_cycle_critic_penalizes_test_only_merge(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir)
            report = run_cycle_critic(
                state_dir,
                cycle_number=70,
                blocked=False,
                blocking_reasons=[],
                merge_verdict="MERGED",
                changed_files=["game/tests/player_health.test.ts"],
            )

        self.assertEqual(report.scores["player_visible"], 1)
        self.assertIn("proposal_quality", report.scores)
        self.assertIn("game/src/", report.next_cycle_constraint)

    def test_write_cycle_critic_persists_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir)
            report = run_cycle_critic(
                state_dir,
                cycle_number=5,
                blocked=True,
                blocking_reasons=["lint failed"],
                merge_verdict=None,
                changed_files=[],
            )
            path = write_cycle_critic(state_dir, 5, report)
            data = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(data["source"], "deterministic")
        self.assertTrue(data["next_cycle_constraint"])

    def test_run_cycle_critic_scores_supported_proposal_board(self) -> None:
        primary = parse_agent_proposal(
            "enemy_designer",
            "Title: Lantern Leech\nGoal: Create a visible threat.",
            index=1,
        )
        support = parse_agent_proposal(
            "art_director_concept",
            "Title: Leech Glow\nSupports: enemy_designer-1\nGoal: Make it readable.",
            index=1,
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir)
            save_proposal_board(
                state_dir,
                ProposalBoard(cycle_number=6, proposals=[primary, support], critiques=[], selected_id=primary.id),
            )
            report = run_cycle_critic(
                state_dir,
                cycle_number=6,
                blocked=False,
                blocking_reasons=[],
                merge_verdict=None,
                changed_files=["game/src/engine.ts", "game/src/render.ts"],
            )

        self.assertEqual(report.scores["proposal_quality"], 5)

    def test_run_cycle_critic_penalizes_invalid_proposal_board(self) -> None:
        trivial = parse_agent_proposal(
            "systems_designer",
            "Title: Increase player starting hp from 10 to 15\nGoal: Change a number.",
            index=1,
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir)
            save_proposal_board(state_dir, ProposalBoard(cycle_number=7, proposals=[trivial], critiques=[], selected_id=trivial.id))
            report = run_cycle_critic(
                state_dir,
                cycle_number=7,
                blocked=True,
                blocking_reasons=["Proposal board rejected before Director selection."],
                merge_verdict=None,
                changed_files=[],
            )

        self.assertEqual(report.scores["proposal_quality"], 1)


if __name__ == "__main__":
    unittest.main()
