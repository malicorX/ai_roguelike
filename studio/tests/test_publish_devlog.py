import json
import tempfile
import unittest
from pathlib import Path

from studio.publish_devlog import load_cycles, publish_site


class PublishDevlogTest(unittest.TestCase):
    def test_load_cycles_reads_director_builder_lint_request_and_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir)
            self._write_cycle(
                state_dir,
                1,
                director="Objective: Add HUD turn counter.",
                builder="Proposed changed files:\n- `game/src/render.ts`",
                proposal_lint={"verdict": "PASS", "issues": []},
                request={"branch": "main", "commit": "abc1234", "objective": "Add HUD turn counter."},
                report={"qa": {"verdict": "PASS"}, "design": {"verdict": "BACKLOG"}},
            )

            cycles = load_cycles(state_dir)

        self.assertEqual(len(cycles), 1)
        self.assertEqual(cycles[0].number, 1)
        self.assertEqual(cycles[0].objective, "Add HUD turn counter.")
        self.assertFalse(cycles[0].blocked)

    def test_publish_site_writes_devlog_docs_and_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            state_dir = repo / "studio" / "state"
            out_dir = repo / "site"
            (repo / "VISUAL_STYLE.md").write_text("# Visual Style\n\nReadable grid.\n", encoding="utf-8")
            self._write_cycle(
                state_dir,
                2,
                director="Objective: Improve smoke logging.",
                builder="Implementation summary: add logs.",
                proposal_lint={"verdict": "REWORK", "issues": ["Unknown npm script in Builder proposal: smoke`"]},
                request={"branch": "main", "commit": "def5678", "objective": "Improve smoke logging."},
                report={"qa": {"verdict": "REWORK", "bugs": ["Unknown npm script in Builder proposal: smoke`"]}, "design": {"verdict": "BACKLOG"}},
            )

            result = publish_site(repo, state_dir, out_dir)

            index_html = (out_dir / "devlog" / "index.html").read_text(encoding="utf-8")
            cycle_html = (out_dir / "devlog" / "cycle-0002.html").read_text(encoding="utf-8")
            docs_html = (out_dir / "docs" / "index.html").read_text(encoding="utf-8")
            visual_html = (out_dir / "docs" / "visual-style.html").read_text(encoding="utf-8")

            self.assertTrue(result.devlog_index.is_file())
            self.assertTrue((out_dir / "devlog" / "artifacts" / "cycle-0002-builder.md").is_file())
            self.assertIn("Improve smoke logging.", index_html)
            self.assertIn("blocked", cycle_html.lower())
            self.assertIn("sparky1", index_html)
            self.assertIn("Handoff", index_html)
            self.assertIn("sparky2", index_html)
            self.assertIn("sparky2", docs_html)
            self.assertIn("Readable grid.", visual_html)

    def test_load_cycle_marks_missing_report_as_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir)
            self._write_cycle(
                state_dir,
                3,
                director="Objective: Finish evaluation.",
                builder="builder",
                proposal_lint={"verdict": "PASS", "issues": []},
                request={"branch": "main", "commit": "abc1234", "objective": "Finish evaluation."},
                report=None,
            )

            cycles = load_cycles(state_dir)

        self.assertTrue(cycles[0].blocked)
        self.assertIn("Evaluation report missing.", cycles[0].blocking_reasons)

    def test_publish_site_renders_write_cycle_apply_and_merge_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            state_dir = repo / "studio" / "state"
            out_dir = repo / "site"
            (repo / "VISUAL_STYLE.md").write_text("# Visual Style\n", encoding="utf-8")
            self._write_cycle(
                state_dir,
                4,
                director="Objective: Update render label.",
                builder="Applied diff.",
                proposal_lint={"verdict": "PASS", "issues": []},
                request={
                    "branch": "cycle-0004-update-render-label",
                    "commit": "deadbeef",
                    "objective": "Update render label.",
                    "spec": "Phase 1 write cycle: repository changes were applied on a feature branch before evaluation.",
                },
                report={"qa": {"verdict": "PASS"}, "design": {"verdict": "BACKLOG"}},
            )
            (state_dir / "cycle-0004-apply.json").write_text(
                json.dumps({"branch": "cycle-0004-update-render-label", "commit": "deadbeef", "verdict": "APPLIED"})
                + "\n",
                encoding="utf-8",
            )
            (state_dir / "cycle-0004-merge.json").write_text(
                json.dumps({"branch": "cycle-0004-update-render-label", "commit": "deadbeef", "verdict": "MERGED"})
                + "\n",
                encoding="utf-8",
            )

            publish_site(repo, state_dir, out_dir)
            cycle_html = (out_dir / "devlog" / "cycle-0004.html").read_text(encoding="utf-8")

        self.assertIn("write", cycle_html.lower())
        self.assertIn("MERGED", cycle_html)

    def _write_cycle(
        self,
        state_dir: Path,
        number: int,
        *,
        director: str,
        builder: str,
        proposal_lint: dict,
        request: dict,
        report: dict | None,
    ) -> None:
        state_dir.mkdir(parents=True, exist_ok=True)
        prefix = f"cycle-{number:04d}"
        (state_dir / f"{prefix}-director.md").write_text(director + "\n", encoding="utf-8")
        (state_dir / f"{prefix}-builder.md").write_text(builder + "\n", encoding="utf-8")
        (state_dir / f"{prefix}-proposal-lint.json").write_text(json.dumps(proposal_lint, indent=2) + "\n", encoding="utf-8")
        (state_dir / f"{prefix}-request.json").write_text(json.dumps(request, indent=2) + "\n", encoding="utf-8")
        if report is not None:
            (state_dir / f"{prefix}-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
