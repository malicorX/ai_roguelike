from __future__ import annotations

import json
import subprocess
from enum import StrEnum
from pathlib import Path
from typing import Callable

from eval_lab.evaluate_candidate import evaluate_candidate
from eval_lab.protocol import EvaluationReport, EvaluationRequest

RunCommand = Callable[[list[str]], None]


class EvaluationTarget(StrEnum):
    LOCAL = "local"
    SPARKY2 = "sparky2"


class EvaluationClient:
    def __init__(
        self,
        target: EvaluationTarget,
        *,
        remote_host: str = "sparky2",
        remote_repo: str = "~/ai_roguelike",
        run_command: RunCommand | None = None,
    ) -> None:
        self.target = target
        self.remote_host = remote_host
        self.remote_repo = remote_repo
        self._run_command = run_command or _run_command

    def evaluate(
        self,
        repo_root: Path,
        request: EvaluationRequest,
        state_dir: Path,
        cycle_number: int,
    ) -> EvaluationReport:
        state_dir.mkdir(parents=True, exist_ok=True)
        request_path = state_dir / f"cycle-{cycle_number:04d}-request.json"
        report_path = state_dir / f"cycle-{cycle_number:04d}-report.json"
        request_path.write_text(json.dumps(request.to_dict(), indent=2) + "\n", encoding="utf-8")

        if self.target == EvaluationTarget.LOCAL:
            report = evaluate_candidate(repo_root, request)
            report_path.write_text(json.dumps(report.to_dict(), indent=2) + "\n", encoding="utf-8")
            return report

        self._evaluate_on_sparky2(request_path, report_path, cycle_number)
        return EvaluationReport.from_dict(json.loads(report_path.read_text(encoding="utf-8")))

    def _evaluate_on_sparky2(self, request_path: Path, report_path: Path, cycle_number: int) -> None:
        remote_request = f"{self.remote_repo}/eval_lab/reports/cycle-{cycle_number:04d}-request.json"
        remote_report = f"{self.remote_repo}/eval_lab/reports/cycle-{cycle_number:04d}-report.json"
        self._run_command(
            [
                "ssh",
                self.remote_host,
                f"cd {self.remote_repo} && git fetch -q origin && git merge --ff-only origin/main && mkdir -p eval_lab/reports",
            ]
        )
        self._run_command(["scp", str(request_path), f"{self.remote_host}:{remote_request}"])
        self._run_command(
            [
                "ssh",
                self.remote_host,
                f"cd {self.remote_repo} && python3 -m eval_lab.evaluate_candidate --repo . --request {remote_request} --out {remote_report}",
            ]
        )
        self._run_command(["scp", f"{self.remote_host}:{remote_report}", str(report_path)])


def _run_command(command: list[str]) -> None:
    subprocess.run(command, check=True)
