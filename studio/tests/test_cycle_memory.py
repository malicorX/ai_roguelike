import json
import tempfile
import unittest
from pathlib import Path

from studio.cycle_memory import append_cycle_record, load_backlog_summary, recent_blocker_notes, recent_cycle_summaries


class CycleMemoryTest(unittest.TestCase):
    def test_recent_cycle_summaries_reads_prior_cycle_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir)
            (state_dir / "cycle-0002-director.md").write_text(
                "Objective: Add HUD turn counter.\nReason: readability.\n",
                encoding="utf-8",
            )
            (state_dir / "cycle-0002-reviewer.json").write_text(
                json.dumps({"verdict": "REWORK", "issues": ["Missing test."]}) + "\n",
                encoding="utf-8",
            )
            (state_dir / "cycle-0002-report.json").write_text(
                json.dumps({"qa": {"verdict": "REWORK"}, "design": {"verdict": "BACKLOG"}}) + "\n",
                encoding="utf-8",
            )

            summary = recent_cycle_summaries(state_dir, before_cycle=3, limit=3)

        self.assertIn("Cycle 2", summary)
        self.assertIn("HUD turn counter", summary)
        self.assertIn("reviewer=REWORK", summary)

    def test_load_backlog_summary_reads_latest_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            backlog = repo / "studio" / "backlog.jsonl"
            backlog.parent.mkdir(parents=True)
            backlog.write_text(
                "\n".join(
                    [
                        json.dumps({"title": "Old idea", "status": "done"}),
                        json.dumps({"title": "Screenshot baselines", "status": "backlog"}),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            summary = load_backlog_summary(repo, limit=2)

        self.assertIn("Screenshot baselines", summary)

    def test_append_cycle_record_writes_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            path = append_cycle_record(
                repo,
                cycle_number=4,
                objective="Update render label.",
                blocked=False,
                blocking_reasons=[],
                mode="write",
                merge_verdict="MERGED",
                branch="cycle-0004-update-render-label",
            )

            record = json.loads(path.read_text(encoding="utf-8").strip().splitlines()[-1])

        self.assertEqual(record["cycle"], 4)
        self.assertEqual(record["merge_verdict"], "MERGED")

    def test_recent_blocker_notes_collects_reviewer_issues(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir)
            (state_dir / "cycle-0031-reviewer.json").write_text(
                json.dumps({"verdict": "REWORK", "issues": ["Do not modify main.ts without imports."]}) + "\n",
                encoding="utf-8",
            )
            (state_dir / "cycle-0031-report.json").write_text(
                json.dumps({"qa": {"verdict": "REWORK", "bugs": []}}) + "\n",
                encoding="utf-8",
            )

            notes = recent_blocker_notes(state_dir, before_cycle=32)

        self.assertIn("Cycle 31 reviewer", notes)
        self.assertIn("main.ts", notes)


if __name__ == "__main__":
    unittest.main()
