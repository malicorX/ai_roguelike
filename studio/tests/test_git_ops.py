import subprocess
import tempfile
import unittest
from pathlib import Path

from studio.git_ops import (
    changed_files_against_main,
    create_cycle_branch,
    current_branch,
    discard_branch,
    merge_branch_to_main,
    slugify_objective,
    stage_all_and_commit,
)


class GitOpsTest(unittest.TestCase):
    def test_slugify_objective_normalizes_text(self) -> None:
        self.assertEqual(slugify_objective("Add HUD turn counter!"), "add-hud-turn-counter")

    def test_create_cycle_branch_and_commit(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            _init_repo(repo)
            (repo / "readme.txt").write_text("hello\n", encoding="utf-8")
            _git(repo, "add", "readme.txt")
            _git(repo, "commit", "-m", "init")

            branch = create_cycle_branch(repo, 4, "Add HUD turn counter")
            self.assertEqual(branch, "cycle-0004-add-hud-turn-counter")
            self.assertEqual(current_branch(repo), branch)

            (repo / "readme.txt").write_text("hello\nworld\n", encoding="utf-8")
            commit = stage_all_and_commit(repo, "cycle 4: add hud")
            self.assertTrue(commit)
            self.assertEqual(changed_files_against_main(repo), ["readme.txt"])

    def test_merge_and_discard_branch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            _init_repo(repo)
            (repo / "readme.txt").write_text("hello\n", encoding="utf-8")
            _git(repo, "add", "readme.txt")
            _git(repo, "commit", "-m", "init")

            branch = create_cycle_branch(repo, 5, "Smoke logging")
            (repo / "readme.txt").write_text("hello\nlogs\n", encoding="utf-8")
            stage_all_and_commit(repo, "cycle 5")

            merge_branch_to_main(repo, branch, message="Merge cycle 5")
            self.assertEqual(current_branch(repo), "main")
            self.assertIn("logs", (repo / "readme.txt").read_text(encoding="utf-8"))

            branch_two = create_cycle_branch(repo, 6, "Retry")
            discard_branch(repo, branch_two)
            self.assertEqual(current_branch(repo), "main")


def _init_repo(repo: Path) -> None:
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "test")
    _git(repo, "branch", "-M", "main")


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


if __name__ == "__main__":
    unittest.main()
