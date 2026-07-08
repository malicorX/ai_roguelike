from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

QaVerdict = Literal["PASS", "REWORK"]
DesignVerdict = Literal["PASS", "BACKLOG", "BLOCK"]


@dataclass(frozen=True)
class EvaluationRequest:
    branch: str
    commit: str
    objective: str
    spec: str
    changed_files: list[str] = field(default_factory=list)
    seeds: list[int] = field(default_factory=list)
    focus: list[str] = field(default_factory=list)
    designer_spec: str = ""
    models: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EvaluationRequest:
        return cls(
            branch=str(data["branch"]),
            commit=str(data["commit"]),
            objective=str(data["objective"]),
            spec=str(data["spec"]),
            changed_files=[str(path) for path in data.get("changed_files", [])],
            seeds=[int(seed) for seed in data.get("seeds", [])],
            focus=[str(item) for item in data.get("focus", [])],
            designer_spec=str(data.get("designer_spec", "")),
            models=str(data.get("models", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "branch": self.branch,
            "commit": self.commit,
            "objective": self.objective,
            "spec": self.spec,
            "changed_files": list(self.changed_files),
            "seeds": list(self.seeds),
            "focus": list(self.focus),
        }
        if self.designer_spec:
            payload["designer_spec"] = self.designer_spec
        if self.models:
            payload["models"] = self.models
        return payload


@dataclass(frozen=True)
class QaReport:
    verdict: QaVerdict
    checks: list[str] = field(default_factory=list)
    bugs: list[str] = field(default_factory=list)
    repro_steps: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> QaReport:
        return cls(
            verdict=_qa_verdict(data["verdict"]),
            checks=[str(check) for check in data.get("checks", [])],
            bugs=[str(bug) for bug in data.get("bugs", [])],
            repro_steps=[str(step) for step in data.get("repro_steps", [])],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "checks": list(self.checks),
            "bugs": list(self.bugs),
            "repro_steps": list(self.repro_steps),
        }


@dataclass(frozen=True)
class DesignReport:
    verdict: DesignVerdict
    fun_notes: list[str] = field(default_factory=list)
    balance_notes: list[str] = field(default_factory=list)
    visual_notes: list[str] = field(default_factory=list)
    backlog_suggestions: list[str] = field(default_factory=list)
    evaluation_roles: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DesignReport:
        return cls(
            verdict=_design_verdict(data["verdict"]),
            fun_notes=[str(note) for note in data.get("fun_notes", [])],
            balance_notes=[str(note) for note in data.get("balance_notes", [])],
            visual_notes=[str(note) for note in data.get("visual_notes", [])],
            backlog_suggestions=[str(item) for item in data.get("backlog_suggestions", [])],
            evaluation_roles=dict(data.get("evaluation_roles", {})),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "verdict": self.verdict,
            "fun_notes": list(self.fun_notes),
            "balance_notes": list(self.balance_notes),
            "visual_notes": list(self.visual_notes),
            "backlog_suggestions": list(self.backlog_suggestions),
        }
        if self.evaluation_roles:
            payload["evaluation_roles"] = dict(self.evaluation_roles)
        return payload


@dataclass(frozen=True)
class EvaluationReport:
    request_branch: str
    request_commit: str
    qa: QaReport
    design: DesignReport

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EvaluationReport:
        return cls(
            request_branch=str(data["request_branch"]),
            request_commit=str(data["request_commit"]),
            qa=QaReport.from_dict(data["qa"]),
            design=DesignReport.from_dict(data["design"]),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_branch": self.request_branch,
            "request_commit": self.request_commit,
            "qa": self.qa.to_dict(),
            "design": self.design.to_dict(),
        }

    def blocks_merge(self) -> bool:
        return bool(self.blocking_reasons())

    def blocking_reasons(self) -> list[str]:
        reasons: list[str] = []
        if self.qa.verdict == "REWORK":
            reasons.append("QA requested rework.")
        if self.design.verdict == "BLOCK":
            reasons.append("Design report blocked merge.")
        return reasons


def _qa_verdict(value: Any) -> QaVerdict:
    if value in ("PASS", "REWORK"):
        return value
    raise ValueError(f"Unsupported QA verdict: {value!r}")


def _design_verdict(value: Any) -> DesignVerdict:
    if value in ("PASS", "BACKLOG", "BLOCK"):
        return value
    raise ValueError(f"Unsupported design verdict: {value!r}")
