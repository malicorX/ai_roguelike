import tempfile
import unittest
from pathlib import Path

from studio.proposals import (
    ProposalBoard,
    choose_selected_proposal,
    load_proposal_board,
    parse_agent_proposal,
    parse_proposal_critique,
    proposal_id_from_text,
    render_proposal_context,
    save_proposal_board,
    validate_proposal_board,
    with_selected_proposal,
)


class ProposalBoardTest(unittest.TestCase):
    def test_parse_agent_proposal_reads_structured_fields(self) -> None:
        proposal = parse_agent_proposal(
            "enemy_designer",
            "\n".join(
                [
                    "Title: Lantern Leech",
                    "Goal: Add a monster that hunts light instead of health.",
                    "Player experience: The player learns to manage visibility and distance.",
                    "Implementation hint: Add one enemy type field and render it with a distinct glyph.",
                    "Acceptance: Smoke shows the new glyph and tests cover spawn data.",
                    "Supports: none",
                ]
            ),
            index=1,
        )

        self.assertEqual(proposal.id, "enemy_designer-1")
        self.assertEqual(proposal.title, "Lantern Leech")
        self.assertIn("hunts light", proposal.goal)
        self.assertIn("visibility", proposal.player_experience)
        self.assertIsNone(proposal.supports)

    def test_parse_critique_collects_verdict_and_notes(self) -> None:
        critique = parse_proposal_critique(
            "qa_critic",
            "\n".join(
                [
                    "Verdict: PASS",
                    "- Keep scope to one enemy behavior and one visual marker.",
                    "2. Require a deterministic smoke assertion.",
                ]
            ),
        )

        self.assertEqual(critique.verdict, "PASS")
        self.assertEqual(len(critique.notes), 2)

    def test_parse_critique_reads_note_tags(self) -> None:
        critique = parse_proposal_critique(
            "qa_critic",
            "\n".join(
                [
                    "Verdict: BLOCK",
                    "<note 1> Repulsor Sentinel lacks a deterministic displacement vector.</note>",
                    "<note 2> Add tests in tests/enemy_movement.test.ts.</note>",
                ]
            ),
        )

        self.assertEqual(critique.verdict, "BLOCK")
        self.assertEqual(len(critique.notes), 2)
        self.assertIn("displacement vector", critique.notes[0])

    def test_selected_proposal_skips_trivial_hp_tweak(self) -> None:
        hp = parse_agent_proposal(
            "systems_designer",
            "Title: Increase player starting hp from 10 to 15\nGoal: Change a number.",
            index=1,
        )
        enemy = parse_agent_proposal(
            "enemy_designer",
            "Title: Lantern Leech\nGoal: Create a memorable enemy with a readable behavior.",
            index=2,
        )

        self.assertEqual(choose_selected_proposal([hp, enemy]), "enemy_designer-2")

    def test_board_round_trips_and_renders_context(self) -> None:
        proposal = parse_agent_proposal(
            "enemy_designer",
            "Title: Shield Goblin\nGoal: Add a blocker that forces flanking.",
            index=1,
        )
        critique = parse_proposal_critique("qa_critic", "Verdict: PASS\n- Good single-feature scope.")
        board = ProposalBoard(cycle_number=12, proposals=[proposal], critiques=[critique], selected_id=proposal.id)

        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir)
            save_proposal_board(state_dir, board)
            loaded = load_proposal_board(state_dir, 12)

        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertEqual(loaded.selected_id, proposal.id)
        context = render_proposal_context(loaded)
        self.assertIn("Selected concept", context)
        self.assertIn("Shield Goblin", context)

    def test_validate_proposal_board_rejects_blocked_critique(self) -> None:
        proposal = parse_agent_proposal(
            "enemy_designer",
            "Title: Lantern Leech\nGoal: Create a visible threat.",
            index=1,
        )
        critique = parse_proposal_critique("qa_critic", "Verdict: BLOCK\n- Lantern Leech is too vague to test.")
        board = ProposalBoard(cycle_number=13, proposals=[proposal], critiques=[critique], selected_id=proposal.id)

        issues = validate_proposal_board(board)

        self.assertEqual(len(issues), 1)
        self.assertIn("qa_critic blocked the selected proposal", issues[0])

    def test_choose_selected_proposal_falls_back_when_qa_blocks_named_primary(self) -> None:
        blocked = parse_agent_proposal(
            "enemy_designer",
            "Title: Repulsor Sentinel\nGoal: Punish adjacency with displacement.",
            index=1,
        )
        fallback = parse_agent_proposal(
            "systems_designer",
            "Title: Threat Radius\nGoal: Create a readable danger zone.",
            index=2,
        )
        critique = parse_proposal_critique(
            "qa_critic",
            "Verdict: BLOCK\n- Repulsor Sentinel lacks a deterministic displacement vector.",
        )

        self.assertEqual(choose_selected_proposal([blocked, fallback], critique), "systems_designer-2")

    def test_validate_proposal_board_allows_unblocked_selected_proposal(self) -> None:
        blocked = parse_agent_proposal(
            "enemy_designer",
            "Title: Repulsor Sentinel\nGoal: Punish adjacency with displacement.",
            index=1,
        )
        selected = parse_agent_proposal(
            "systems_designer",
            "Title: Threat Radius\nGoal: Create a readable danger zone.",
            index=2,
        )
        critique = parse_proposal_critique(
            "qa_critic",
            "Verdict: BLOCK\n- Repulsor Sentinel lacks a deterministic displacement vector.",
        )
        board = ProposalBoard(
            cycle_number=17,
            proposals=[blocked, selected],
            critiques=[critique],
            selected_id=selected.id,
        )

        self.assertEqual(validate_proposal_board(board), [])

    def test_validate_proposal_board_rejects_trivial_selected_proposal(self) -> None:
        proposal = parse_agent_proposal(
            "systems_designer",
            "Title: Increase player starting hp from 10 to 15\nGoal: Change a number.",
            index=1,
        )
        board = ProposalBoard(cycle_number=14, proposals=[proposal], critiques=[], selected_id=proposal.id)

        issues = validate_proposal_board(board)

        self.assertEqual(len(issues), 1)
        self.assertIn("trivial", issues[0])

    def test_validate_proposal_board_rejects_missing_support_target(self) -> None:
        art = parse_agent_proposal(
            "art_director_concept",
            "Title: Leech Glow\nSupports: enemy_designer-99\nGoal: Give the leech a readable glow.",
            index=1,
        )
        board = ProposalBoard(cycle_number=15, proposals=[art], critiques=[], selected_id=art.id)

        issues = validate_proposal_board(board)

        self.assertTrue(any("references missing proposal" in issue for issue in issues))
        self.assertTrue(any("support-only" in issue for issue in issues))

    def test_director_text_can_select_proposal_id(self) -> None:
        first = parse_agent_proposal("enemy_designer", "Title: First\nGoal: One.", index=1)
        second = parse_agent_proposal("systems_designer", "Title: Second\nGoal: Two.", index=2)
        board = ProposalBoard(cycle_number=15, proposals=[first, second], critiques=[], selected_id=first.id)

        selected_id = proposal_id_from_text("Proposal: systems_designer-2\nObjective: Build second.", board)
        updated = with_selected_proposal(board, selected_id)

        self.assertEqual(selected_id, "systems_designer-2")
        self.assertEqual(updated.selected_id, "systems_designer-2")

    def test_selection_prefers_primary_proposal_over_supporting_visual(self) -> None:
        enemy = parse_agent_proposal(
            "enemy_designer",
            "Title: Lantern Leech\nGoal: Create a memorable enemy.",
            index=1,
        )
        art = parse_agent_proposal(
            "art_director_concept",
            "Title: Leech Glow\nSupports: enemy_designer-1\nGoal: Give the leech a readable glow.",
            index=1,
        )

        self.assertEqual(choose_selected_proposal([art, enemy]), "enemy_designer-1")

    def test_render_context_groups_supporting_concepts_with_selected_proposal(self) -> None:
        enemy = parse_agent_proposal(
            "enemy_designer",
            "Title: Lantern Leech\nGoal: Create a memorable enemy.",
            index=1,
        )
        art = parse_agent_proposal(
            "art_director_concept",
            "Title: Leech Glow\nSupports: enemy_designer-1\nGoal: Give the leech a readable glow.",
            index=1,
        )
        board = ProposalBoard(cycle_number=16, proposals=[enemy, art], critiques=[], selected_id=enemy.id)

        context = render_proposal_context(board)

        self.assertIn("Supporting concepts for selected proposal", context)
        self.assertIn("Leech Glow", context)


if __name__ == "__main__":
    unittest.main()
