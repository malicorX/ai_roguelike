import unittest

from eval_lab.protocol import (
    DesignReport,
    EvaluationReport,
    EvaluationRequest,
    QaReport,
)


class EvaluationProtocolTest(unittest.TestCase):
    def test_request_round_trips_through_plain_data(self) -> None:
        request = EvaluationRequest.from_dict(
            {
                "branch": "cycle-1-add-enemy",
                "commit": "abc1234",
                "objective": "Add a wandering enemy",
                "spec": "The enemy should pressure the player without blocking movement tests.",
                "changed_files": ["game/src/engine.ts"],
                "seeds": [1, 7, 42],
                "focus": ["combat", "balance"],
            }
        )

        self.assertEqual(request.branch, "cycle-1-add-enemy")
        self.assertEqual(request.seeds, [1, 7, 42])
        self.assertEqual(
            request.to_dict(),
            {
                "branch": "cycle-1-add-enemy",
                "commit": "abc1234",
                "objective": "Add a wandering enemy",
                "spec": "The enemy should pressure the player without blocking movement tests.",
                "changed_files": ["game/src/engine.ts"],
                "seeds": [1, 7, 42],
                "focus": ["combat", "balance"],
            },
        )

    def test_report_marks_qa_rework_as_blocking(self) -> None:
        report = EvaluationReport(
            request_branch="cycle-1-add-enemy",
            request_commit="abc1234",
            qa=QaReport(verdict="REWORK", bugs=["Crash after death"], repro_steps=["Die twice"]),
            design=DesignReport(verdict="PASS", fun_notes=["Enemy pressure is clear"]),
        )

        self.assertTrue(report.blocks_merge())
        self.assertEqual(report.blocking_reasons(), ["QA requested rework."])

    def test_report_marks_visual_block_as_blocking(self) -> None:
        report = EvaluationReport(
            request_branch="cycle-2-poison",
            request_commit="def5678",
            qa=QaReport(verdict="PASS"),
            design=DesignReport(
                verdict="BLOCK",
                visual_notes=["Poison cloud hides the player sprite."],
            ),
        )

        self.assertTrue(report.blocks_merge())
        self.assertEqual(report.blocking_reasons(), ["Design report has blocking visual issues."])

    def test_passed_report_round_trips_through_plain_data(self) -> None:
        report = EvaluationReport(
            request_branch="cycle-3-ui",
            request_commit="fedcba9",
            qa=QaReport(verdict="PASS", checks=["npm test", "npm run build"]),
            design=DesignReport(verdict="PASS", fun_notes=["Readable status line"]),
        )

        self.assertFalse(report.blocks_merge())
        self.assertEqual(
            EvaluationReport.from_dict(report.to_dict()),
            report,
        )


if __name__ == "__main__":
    unittest.main()
