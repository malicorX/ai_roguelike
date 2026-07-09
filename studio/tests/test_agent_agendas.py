import tempfile
import unittest
from pathlib import Path

from studio.agent_agendas import (
    load_agent_agendas,
    record_cycle_outcome,
    record_proposal_board,
    record_proposal_selection,
    render_agenda_context,
)
from studio.proposals import ProposalBoard, parse_agent_proposal, parse_proposal_critique


class AgentAgendaTest(unittest.TestCase):
    def test_load_agent_agendas_returns_default_missions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            agendas = load_agent_agendas(Path(tmpdir))

        self.assertIn("enemy_designer", agendas)
        self.assertIn("memorable", agendas["enemy_designer"].mission)

    def test_record_proposal_board_updates_role_counters(self) -> None:
        proposal = parse_agent_proposal(
            "enemy_designer",
            "Title: Lantern Leech\nGoal: Create a visible threat.",
            index=1,
        )
        critique = parse_proposal_critique("qa_critic", "Verdict: PASS\n- Clear acceptance.")
        board = ProposalBoard(cycle_number=3, proposals=[proposal], critiques=[critique], selected_id=proposal.id)

        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir)
            record_proposal_board(state_dir, board)
            agendas = load_agent_agendas(state_dir)

        self.assertEqual(agendas["enemy_designer"].proposed, 1)
        self.assertEqual(agendas["enemy_designer"].selected, 0)
        self.assertEqual(agendas["qa_critic"].proposed, 1)

    def test_record_proposal_selection_updates_director_selected_author(self) -> None:
        proposal = parse_agent_proposal(
            "enemy_designer",
            "Title: Lantern Leech\nGoal: Create a visible threat.",
            index=1,
        )
        support = parse_agent_proposal(
            "art_director_concept",
            "Title: Leech Glow\nSupports: enemy_designer-1\nGoal: Make it readable.",
            index=1,
        )
        board = ProposalBoard(cycle_number=3, proposals=[proposal, support], critiques=[], selected_id=proposal.id)

        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir)
            record_proposal_board(state_dir, board)
            record_proposal_selection(state_dir, board)
            agendas = load_agent_agendas(state_dir)

        self.assertEqual(agendas["enemy_designer"].selected, 1)
        self.assertIn("Leech Glow", "; ".join(agendas["enemy_designer"].recent_feedback))

    def test_record_cycle_outcome_updates_selected_author_feedback(self) -> None:
        proposal = parse_agent_proposal(
            "systems_designer",
            "Title: Echo Step\nGoal: Make movement generate risk.",
            index=1,
        )
        board = ProposalBoard(cycle_number=4, proposals=[proposal], critiques=[], selected_id=proposal.id)

        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir)
            record_proposal_board(state_dir, board)
            record_cycle_outcome(state_dir, board, merged=False, blocked=True, feedback=["npm test failed"])
            context = render_agenda_context(state_dir)

        self.assertIn("systems_designer", context)
        self.assertIn("blocked=1", context)
        self.assertIn("npm test failed", context)


if __name__ == "__main__":
    unittest.main()
