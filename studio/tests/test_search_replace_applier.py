import tempfile
import unittest
from pathlib import Path

from studio.patch_applier import PatchExtractError
from studio.search_replace_applier import (
    apply_builder_patch,
    extract_builder_patch,
    validate_builder_patch,
)
from studio.write_scope import allowed_builder_paths, validate_write_scope


class SearchReplaceApplierTest(unittest.TestCase):
    def test_extract_and_apply_search_replace(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            target = repo / "game" / "src" / "engine.ts"
            target.parent.mkdir(parents=True)
            target.write_text(
                "\n".join(
                    [
                        "export function stepGame(game: GameState, action: GameAction): GameState {",
                        "  return movePlayer(game, action);",
                        "}",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            builder_output = """Summary

```search_replace game/src/engine.ts
<<<<<<< SEARCH
export function stepGame(game: GameState, action: GameAction): GameState {
  return movePlayer(game, action);
}
=======
export function stepGame(game: GameState, action: GameAction): GameState {
  const next = movePlayer(game, action);
  return next;
}
>>>>>>> REPLACE
```
"""
            patch = extract_builder_patch(builder_output)
            issues = validate_builder_patch(repo, patch)
            self.assertEqual(issues, [])
            apply_builder_patch(repo, patch)
            updated = target.read_text(encoding="utf-8")
            self.assertIn("const next = movePlayer(game, action);", updated)

    def test_validate_rejects_ambiguous_search(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            target = repo / "game" / "src" / "main.ts"
            target.parent.mkdir(parents=True)
            target.write_text("const x = 1;\nconst x = 1;\n", encoding="utf-8")
            patch = extract_builder_patch(
                """```search_replace game/src/main.ts
<<<<<<< SEARCH
const x = 1;
=======
const x = 2;
>>>>>>> REPLACE
```"""
            )
            issues = validate_builder_patch(repo, patch)
            self.assertTrue(any("unique" in issue for issue in issues))

    def test_extract_new_file_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            patch = extract_builder_patch(
                """```new_file game/src/hud.ts
export const HUD = true;
```"""
            )
            issues = validate_builder_patch(repo, patch)
            self.assertEqual(issues, [])
            apply_builder_patch(repo, patch)
            self.assertTrue((repo / "game/src/hud.ts").is_file())

    def test_falls_back_to_unified_diff(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            target = repo / "readme.txt"
            target.write_text("hello\n", encoding="utf-8")
            patch = extract_builder_patch(
                """```diff
--- a/readme.txt
+++ b/readme.txt
@@ -1 +1 @@
-hello
+hello world
```"""
            )
            self.assertIsNotNone(patch.unified_diff)


class WriteScopeTest(unittest.TestCase):
    def test_validate_write_scope_rejects_mixed_src_and_tests(self) -> None:
        designer = "\n".join(
            [
                "# In-scope files",
                "- `game/src/engine.ts`",
                "- `game/tests/enemy_movement.test.ts`",
                "",
                "# Out of scope",
                "- other",
            ]
        )
        issues = validate_write_scope(designer)
        self.assertEqual(len(issues), 1)
        self.assertIn("mixes implementation and test", issues[0])

    def test_allowed_builder_paths_prefers_primary_implementation_file(self) -> None:
        designer = "\n".join(
            [
                "# In-scope files",
                "- `game/src/engine.ts`",
            ]
        )
        self.assertEqual(allowed_builder_paths(designer), {"game/src/engine.ts"})


if __name__ == "__main__":
    unittest.main()
