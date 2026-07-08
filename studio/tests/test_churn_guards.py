import json
import tempfile
import unittest
from pathlib import Path

from studio.churn_guards import (
    consecutive_test_only_merges,
    has_player_visible_change,
    is_test_only_change,
    is_test_only_designer_spec,
    is_test_only_objective,
    requires_src_change,
)


class ChurnGuardsTest(unittest.TestCase):
    def test_is_test_only_change(self) -> None:
        self.assertTrue(is_test_only_change(["game/tests/foo.test.ts"]))
        self.assertFalse(is_test_only_change(["game/src/engine.ts"]))
        self.assertFalse(is_test_only_change(["game/tests/foo.test.ts", "game/src/engine.ts"]))

    def test_has_player_visible_change(self) -> None:
        self.assertTrue(has_player_visible_change(["game/src/engine.ts"]))
        self.assertTrue(has_player_visible_change(["game/src/main.ts"]))
        self.assertFalse(has_player_visible_change(["game/tests/foo.test.ts"]))
        self.assertFalse(has_player_visible_change(["game/src/testHarness.ts"]))

    def test_is_test_only_objective(self) -> None:
        self.assertTrue(is_test_only_objective("Add unit test for enemy movement in game/tests/enemy.test.ts"))
        self.assertFalse(is_test_only_objective("Increase player hp in game/src/engine.ts"))

    def test_is_test_only_designer_spec(self) -> None:
        spec = "\n".join(
            [
                "3. **In-scope files**",
                "- `game/tests/player.test.ts`",
                "4. **Out of scope**",
                "- `game/src/engine.ts`",
            ]
        )
        self.assertTrue(is_test_only_designer_spec(spec))

    def test_requires_src_change_after_test_only_merge(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir)
            self._write_merge(state_dir, 68, ["game/tests/player_health.test.ts"])
            self.assertEqual(consecutive_test_only_merges(state_dir, before_cycle=69), 1)
            self.assertTrue(requires_src_change(state_dir, before_cycle=69))

    def _write_merge(self, state_dir: Path, cycle_number: int, changed_files: list[str]) -> None:
        prefix = f"cycle-{cycle_number:04d}"
        (state_dir / f"{prefix}-merge.json").write_text(
            json.dumps({"verdict": "MERGED", "branch": "test", "commit": "abc1234"}) + "\n",
            encoding="utf-8",
        )
        (state_dir / f"{prefix}-apply.json").write_text(
            json.dumps({"changed_files": changed_files, "verdict": "APPLIED"}) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    unittest.main()
