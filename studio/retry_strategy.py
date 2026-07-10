from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from eval_lab.protocol import EvaluationReport

DEFAULT_MAX_BUILDER_ONLY_RETRIES = 4
# Local Agents-A1 on sparky1: fast and already proven for merge-quality patches.
STRONGER_BUILDER_MODEL = "hf.co/InternScience/Agents-A1-Q4_K_M-GGUF:latest"


class RetryStage(StrEnum):
    FROM_BUILDER = "from_builder"
    FROM_DESIGNER = "from_designer"
    FROM_DIRECTOR = "from_director"
    FULL = "full"


_DOWNSTREAM_SUFFIXES: tuple[str, ...] = (
    "report.json",
    "request.json",
    "apply.json",
    "merge.json",
    "reviewer.json",
    "proposal-lint.json",
    "builder.md",
    "process.md",
    "critic.json",
)

_FULL_CLEAR_SUFFIXES: tuple[str, ...] = _DOWNSTREAM_SUFFIXES + (
    "designer.md",
    "director.md",
    "proposals.json",
    "proposals.md",
)


@dataclass(frozen=True)
class CycleRetryState:
    builder_only_retries: int = 0
    last_blocker_feedback: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> CycleRetryState:
        raw = payload.get("builder_only_retries", 0)
        feedback_raw = payload.get("last_blocker_feedback", [])
        feedback: tuple[str, ...] = ()
        if isinstance(feedback_raw, list):
            feedback = tuple(str(item).strip() for item in feedback_raw if str(item).strip())
        return cls(
            builder_only_retries=int(raw) if isinstance(raw, (int, float)) else 0,
            last_blocker_feedback=feedback,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "builder_only_retries": self.builder_only_retries,
            "last_blocker_feedback": list(self.last_blocker_feedback),
        }


def retry_state_path(state_dir: Path, cycle_number: int) -> Path:
    return state_dir / f"cycle-{cycle_number:04d}-retry-state.json"


def load_retry_state(state_dir: Path, cycle_number: int) -> CycleRetryState:
    path = retry_state_path(state_dir, cycle_number)
    if not path.is_file():
        return CycleRetryState()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return CycleRetryState()
    if not isinstance(payload, dict):
        return CycleRetryState()
    return CycleRetryState.from_dict(payload)


def save_retry_state(state_dir: Path, cycle_number: int, state: CycleRetryState) -> None:
    path = retry_state_path(state_dir, cycle_number)
    path.write_text(json.dumps(state.to_dict(), indent=2) + "\n", encoding="utf-8")


def failure_signals_from_report(report: EvaluationReport) -> list[str]:
    signals = list(report.blocking_reasons())
    signals.extend(report.qa.checks)
    signals.extend(report.qa.bugs)
    signals.extend(report.qa.repro_steps)
    return signals


def failure_signals_from_state(state_dir: Path, cycle_number: int) -> list[str]:
    report_path = state_dir / f"cycle-{cycle_number:04d}-report.json"
    if not report_path.is_file():
        return []
    try:
        report = EvaluationReport.from_dict(json.loads(report_path.read_text(encoding="utf-8")))
    except json.JSONDecodeError:
        return []
    return failure_signals_from_report(report)


def capture_blocker_feedback(state_dir: Path, cycle_number: int) -> list[str]:
    prefix = f"cycle-{cycle_number:04d}"
    feedback: list[str] = []
    seen: set[str] = set()

    reviewer_path = state_dir / f"{prefix}-reviewer.json"
    if reviewer_path.is_file():
        try:
            reviewer = json.loads(reviewer_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            reviewer = {}
        if isinstance(reviewer, dict):
            for issue in reviewer.get("issues", []):
                text = str(issue).strip()
                if text and text not in seen:
                    seen.add(text)
                    feedback.append(text)

    for signal in failure_signals_from_state(state_dir, cycle_number):
        text = signal.strip()
        if text and text not in seen:
            seen.add(text)
            feedback.append(text)

    return feedback[:16]


def choose_retry_stage(
    signals: list[str],
    retry_state: CycleRetryState,
    *,
    max_builder_only_retries: int = DEFAULT_MAX_BUILDER_ONLY_RETRIES,
) -> tuple[RetryStage, CycleRetryState]:
    stage = _infer_retry_stage(signals, retry_state=retry_state, max_builder_only_retries=max_builder_only_retries)
    if stage == RetryStage.FROM_BUILDER:
        return stage, CycleRetryState(
            builder_only_retries=retry_state.builder_only_retries + 1,
            last_blocker_feedback=retry_state.last_blocker_feedback,
        )
    return stage, CycleRetryState(builder_only_retries=0, last_blocker_feedback=())


def suffixes_for_stage(stage: RetryStage) -> tuple[str, ...]:
    if stage == RetryStage.FROM_BUILDER:
        return _DOWNSTREAM_SUFFIXES
    if stage == RetryStage.FROM_DESIGNER:
        return _DOWNSTREAM_SUFFIXES + ("designer.md",)
    if stage == RetryStage.FROM_DIRECTOR:
        return _DOWNSTREAM_SUFFIXES + ("designer.md", "director.md")
    return _FULL_CLEAR_SUFFIXES


def clear_cycle_for_retry(
    state_dir: Path,
    cycle_number: int,
    *,
    stage: RetryStage = RetryStage.FULL,
    reset_run_log: bool = False,
) -> list[str]:
    prefix = f"cycle-{cycle_number:04d}"
    cleared: list[str] = []
    for suffix in suffixes_for_stage(stage):
        path = state_dir / f"{prefix}-{suffix}"
        if path.is_file():
            path.unlink()
            cleared.append(suffix)
    run_log = state_dir / f"{prefix}-run.log"
    if reset_run_log or stage == RetryStage.FULL:
        if run_log.is_file():
            run_log.unlink()
            cleared.append("run.log")
    elif run_log.is_file():
        with run_log.open("a", encoding="utf-8") as handle:
            handle.write(f"until-green retry ({stage.value})\n")
    return cleared


def prepare_until_green_retry(
    state_dir: Path,
    cycle_number: int,
    *,
    max_builder_only_retries: int = DEFAULT_MAX_BUILDER_ONLY_RETRIES,
) -> tuple[RetryStage, list[str], CycleRetryState]:
    feedback = capture_blocker_feedback(state_dir, cycle_number)
    signals = failure_signals_from_state(state_dir, cycle_number)
    retry_state = load_retry_state(state_dir, cycle_number)
    stage, next_state = choose_retry_stage(
        signals,
        retry_state,
        max_builder_only_retries=max_builder_only_retries,
    )
    cleared = clear_cycle_for_retry(state_dir, cycle_number, stage=stage)
    saved = CycleRetryState(
        builder_only_retries=next_state.builder_only_retries,
        last_blocker_feedback=tuple(feedback) if stage == RetryStage.FROM_BUILDER else (),
    )
    save_retry_state(state_dir, cycle_number, saved)
    return stage, cleared, saved


def should_use_stronger_builder(retry_state: CycleRetryState) -> bool:
    return retry_state.builder_only_retries > 0


def _infer_retry_stage(
    signals: list[str],
    *,
    retry_state: CycleRetryState,
    max_builder_only_retries: int,
) -> RetryStage:
    text = " ".join(signals).lower()
    if "proposal board" in text:
        return RetryStage.FULL
    if "director picked" in text or "director objective" in text or "gameplay churn guard (director)" in text:
        return RetryStage.FROM_DIRECTOR
    if "designer spec" in text or "write scope guard" in text or "gameplay churn guard (designer)" in text:
        return RetryStage.FROM_DESIGNER
    if _is_builder_stage_failure(text):
        if retry_state.builder_only_retries >= max_builder_only_retries:
            return RetryStage.FROM_DESIGNER
        return RetryStage.FROM_BUILDER
    if "reviewer requested rework" in text:
        if retry_state.builder_only_retries >= max_builder_only_retries:
            return RetryStage.FROM_DESIGNER
        return RetryStage.FROM_BUILDER
    if "qa requested rework" in text:
        if retry_state.builder_only_retries >= max_builder_only_retries:
            return RetryStage.FROM_DESIGNER
        return RetryStage.FROM_BUILDER
    return RetryStage.FULL


def _is_builder_stage_failure(text: str) -> bool:
    markers = (
        "builder patch validation",
        "builder proposal lint",
        "builder output",
        "builder role failed",
        "builder diff validation",
        "unified diff fenced block",
        "out-of-scope path",
        "patch validation failed",
        "patch does not apply",
        "hunk ",
    )
    return any(marker in text for marker in markers)
