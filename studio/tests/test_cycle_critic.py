import json
import tempfile
import unittest
from pathlib import Path

from studio.cycle_critic import run_cycle_critic, write_cycle_critic


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


if __name__ == "__main__":
    unittest.main()
