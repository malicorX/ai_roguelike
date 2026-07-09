from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from studio.proposals import ProposalBoard


DEFAULT_AGENT_AGENDAS: dict[str, dict[str, str]] = {
    "enemy_designer": {
        "mission": "Create enemies with memorable behavior, readable counters, and distinct tactical pressure.",
        "current_goal": "Pitch enemies that change how the player moves or prioritizes threats.",
    },
    "systems_designer": {
        "mission": "Create small mechanics that generate decisions instead of passive stat changes.",
        "current_goal": "Pitch mechanics that can be observed, tested, and expanded by later cycles.",
    },
    "art_director_concept": {
        "mission": "Give mechanics visual identity through glyphs, color, layout, and readable feedback.",
        "current_goal": "Pitch visual treatments that make a mechanic understandable at a glance.",
    },
    "qa_critic": {
        "mission": "Protect the studio from vague, invisible, untestable, or trivial concepts.",
        "current_goal": "Push proposals toward observable acceptance criteria and focused scope.",
    },
}


@dataclass
class AgentAgenda:
    role: str
    mission: str
    current_goal: str
    proposed: int = 0
    selected: int = 0
    merged: int = 0
    blocked: int = 0
    recent_titles: list[str] = field(default_factory=list)
    recent_feedback: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "mission": self.mission,
            "current_goal": self.current_goal,
            "proposed": self.proposed,
            "selected": self.selected,
            "merged": self.merged,
            "blocked": self.blocked,
            "recent_titles": list(self.recent_titles),
            "recent_feedback": list(self.recent_feedback),
        }

    @classmethod
    def from_dict(cls, role: str, data: dict[str, Any]) -> AgentAgenda:
        defaults = DEFAULT_AGENT_AGENDAS.get(role, {})
        return cls(
            role=role,
            mission=str(data.get("mission") or defaults.get("mission") or ""),
            current_goal=str(data.get("current_goal") or defaults.get("current_goal") or ""),
            proposed=int(data.get("proposed", 0)),
            selected=int(data.get("selected", 0)),
            merged=int(data.get("merged", 0)),
            blocked=int(data.get("blocked", 0)),
            recent_titles=[str(item) for item in data.get("recent_titles", []) if str(item).strip()],
            recent_feedback=[str(item) for item in data.get("recent_feedback", []) if str(item).strip()],
        )


def agenda_path(state_dir: Path) -> Path:
    return state_dir / "agent-agendas.json"


def load_agent_agendas(state_dir: Path) -> dict[str, AgentAgenda]:
    path = agenda_path(state_dir)
    raw: dict[str, Any] = {}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            loaded = {}
        if isinstance(loaded, dict):
            raw = loaded

    agendas: dict[str, AgentAgenda] = {}
    for role, defaults in DEFAULT_AGENT_AGENDAS.items():
        data = raw.get(role, {})
        agendas[role] = AgentAgenda.from_dict(role, data if isinstance(data, dict) else defaults)
    return agendas


def save_agent_agendas(state_dir: Path, agendas: dict[str, AgentAgenda]) -> None:
    path = agenda_path(state_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({role: agenda.to_dict() for role, agenda in sorted(agendas.items())}, indent=2) + "\n",
        encoding="utf-8",
    )


def render_agenda_context(state_dir: Path) -> str:
    agendas = load_agent_agendas(state_dir)
    lines = ["Specialist agent agendas:"]
    for role, agenda in agendas.items():
        lines.extend(
            [
                f"- {role}",
                f"  Mission: {agenda.mission}",
                f"  Current goal: {agenda.current_goal}",
                f"  Record: proposed={agenda.proposed}, selected={agenda.selected}, merged={agenda.merged}, blocked={agenda.blocked}",
            ]
        )
        if agenda.recent_titles:
            lines.append(f"  Recent titles: {', '.join(agenda.recent_titles[-3:])}")
        if agenda.recent_feedback:
            lines.append(f"  Recent feedback: {'; '.join(agenda.recent_feedback[-2:])}")
    return "\n".join(lines)


def record_proposal_board(state_dir: Path, board: ProposalBoard) -> None:
    agendas = load_agent_agendas(state_dir)
    for proposal in board.proposals:
        agenda = agendas.get(proposal.author_role)
        if agenda is None:
            continue
        agenda.proposed += 1
        agenda.recent_titles = _append_limited(agenda.recent_titles, proposal.title)
    for critique in board.critiques:
        agenda = agendas.get(critique.author_role)
        if agenda is None:
            continue
        agenda.proposed += 1
        if critique.notes:
            agenda.recent_feedback = _append_limited(agenda.recent_feedback, "; ".join(critique.notes[:2]))
    save_agent_agendas(state_dir, agendas)


def record_proposal_selection(state_dir: Path, board: ProposalBoard | None) -> None:
    if board is None:
        return
    selected = board.selected_proposal()
    if selected is None:
        return
    agendas = load_agent_agendas(state_dir)
    agenda = agendas.get(selected.author_role)
    if agenda is None:
        return
    agenda.selected += 1
    supporting_titles = [proposal.title for proposal in board.supporting_proposals()]
    if supporting_titles:
        agenda.recent_feedback = _append_limited(
            agenda.recent_feedback,
            f"Selected with support: {', '.join(supporting_titles[:3])}",
        )
    save_agent_agendas(state_dir, agendas)


def record_cycle_outcome(
    state_dir: Path,
    board: ProposalBoard | None,
    *,
    merged: bool,
    blocked: bool,
    feedback: list[str],
) -> None:
    if board is None:
        return
    selected = board.selected_proposal()
    if selected is None:
        return
    agendas = load_agent_agendas(state_dir)
    agenda = agendas.get(selected.author_role)
    if agenda is None:
        return
    if merged:
        agenda.merged += 1
        agenda.recent_feedback = _append_limited(agenda.recent_feedback, f"Merged: {selected.title}")
    elif blocked:
        agenda.blocked += 1
        if feedback:
            agenda.recent_feedback = _append_limited(agenda.recent_feedback, "; ".join(feedback[:2]))
    save_agent_agendas(state_dir, agendas)


def _append_limited(items: list[str], item: str, *, limit: int = 8) -> list[str]:
    cleaned = item.strip()
    if not cleaned:
        return items[-limit:]
    return [*items, cleaned][-limit:]
