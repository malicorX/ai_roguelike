import subprocess
import tempfile
import unittest
from pathlib import Path

from studio.patch_applier import PatchApplyError, PatchExtractError, apply_unified_diff, diff_paths, extract_unified_diff, repair_unified_diff


class PatchApplierTest(unittest.TestCase):
    def test_extract_unified_diff_reads_fenced_block(self) -> None:
        text = """Summary: add line
```diff
diff --git a/readme.txt b/readme.txt
--- a/readme.txt
+++ b/readme.txt
@@ -1 +1,2 @@
 hello
+world
```
"""
        diff = extract_unified_diff(text)
        self.assertIn("diff --git a/readme.txt", diff)
        self.assertEqual(diff_paths(diff), ["readme.txt"])

    def test_extract_unified_diff_requires_diff_block(self) -> None:
        with self.assertRaises(PatchExtractError):
            extract_unified_diff("Only a proposal without a diff.")

    def test_extract_unified_diff_skips_non_diff_fenced_blocks(self) -> None:
        text = """Summary
```bash
npm test
```
```diff
--- a/readme.txt
+++ b/readme.txt
@@ -1 +1,2 @@
 hello
+world
```
"""
        diff = extract_unified_diff(text)
        self.assertIn("readme.txt", diff)

    def test_apply_unified_diff_updates_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            _init_repo(repo)
            (repo / "readme.txt").write_text("hello\n", encoding="utf-8")
            _git(repo, "add", "readme.txt")
            _git(repo, "commit", "-m", "init")

            diff = """diff --git a/readme.txt b/readme.txt
--- a/readme.txt
+++ b/readme.txt
@@ -1 +1,2 @@
 hello
+world
"""
            apply_unified_diff(repo, diff)
            self.assertEqual((repo / "readme.txt").read_text(encoding="utf-8"), "hello\nworld\n")

    def test_apply_unified_diff_rejects_invalid_patch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            _init_repo(repo)
            (repo / "readme.txt").write_text("hello\n", encoding="utf-8")
            _git(repo, "add", "readme.txt")
            _git(repo, "commit", "-m", "init")

            with self.assertRaises(PatchApplyError):
                apply_unified_diff(repo, "diff --git a/missing.txt b/missing.txt\n")

    def test_repair_unified_diff_reanchors_misaligned_hunk(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            _init_repo(repo)
            target = repo / "game" / "tests" / "engine.test.ts"
            target.parent.mkdir(parents=True)
            target.write_text(
                "\n".join(
                    [
                        'describe("suite", () => {',
                        '  it("existing", () => {',
                        "    expect(true).toBe(true);",
                        "  });",
                        "});",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            _git(repo, "add", ".")
            _git(repo, "commit", "-m", "init")

            diff = """--- a/game/tests/engine.test.ts
+++ b/game/tests/engine.test.ts
@@ -99,3 +99,7 @@
     expect(true).toBe(true);
   });
+
+  it("added", () => {
+    expect(1).toBe(1);
+  });
 });
"""
            repaired = repair_unified_diff(repo, diff)
            self.assertIn("@@ -3,3 +3,6 @@", repaired)
            apply_unified_diff(repo, diff)
            self.assertIn('it("added"', target.read_text(encoding="utf-8"))


def _init_repo(repo: Path) -> None:
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "test")
    _git(repo, "branch", "-M", "main")


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


if __name__ == "__main__":
    unittest.main()
