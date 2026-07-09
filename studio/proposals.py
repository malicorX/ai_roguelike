from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PRIMARY_PROPOSAL_ROLES = ("enemy_designer", "systems_designer")
SUPPORT_PROPOSAL_ROLES = ("art_director_concept",)
PROPOSAL_ROLES = (*PRIMARY_PROPOSAL_ROLES, *SUPPORT_PROPOSAL_ROLES)
CRITIQUE_ROLE = "qa_critic"


@dataclass(frozen=True)
class AgentProposal:
    id: str
    author_role: str
    title: str
    goal: str
    player_experience: str
    implementation_hint: str
    acceptance: str
    supports: str | None
    raw: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "author_role": self.author_role,
            "title": self.title,
            "goal": self.goal,
            "player_experience": self.player_experience,
            "implementation_hint": self.implementation_hint,
            "acceptance": self.acceptance,
            "supports": self.supports,
            "raw": self.raw,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentProposal:
        return cls(
            id=str(data.get("id", "")),
            author_role=str(data.get("author_role", "")),
            title=str(data.get("title", "")),
            goal=str(data.get("goal", "")),
            player_experience=str(data.get("player_experience", "")),
            implementation_hint=str(data.get("implementation_hint", "")),
            acceptance=str(data.get("acceptance", "")),
            supports=str(data.get("supports")) if data.get("supports") else None,
            raw=str(data.get("raw", "")),
        )


@dataclass(frozen=True)
class ProposalCritique:
    author_role: str
    verdict: str
    notes: list[str]
    raw: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "author_role": self.author_role,
            "verdict": self.verdict,
            "notes": list(self.notes),
            "raw": self.raw,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProposalCritique:
        notes = data.get("notes", [])
        return cls(
            author_role=str(data.get("author_role", "")),
            verdict=str(data.get("verdict", "")),
            notes=[str(note) for note in notes] if isinstance(notes, list) else [],
            raw=str(data.get("raw", "")),
        )


@dataclass(frozen=True)
class ProposalBoard:
    cycle_number: int
    proposals: list[AgentProposal]
    critiques: list[ProposalCritique]
    selected_id: str | None = None

    def selected_proposal(self) -> AgentProposal | None:
        if self.selected_id:
            for proposal in self.proposals:
                if proposal.id == self.selected_id:
                    return proposal
        return self.proposals[0] if self.proposals else None

    def supporting_proposals(self) -> list[AgentProposal]:
        selected = self.selected_proposal()
        if selected is None:
            return []
        return [proposal for proposal in self.proposals if proposal.supports == selected.id]

    def to_dict(self) -> dict[str, Any]:
        return {
            "cycle_number": self.cycle_number,
            "selected_id": self.selected_id,
            "proposals": [proposal.to_dict() for proposal in self.proposals],
            "critiques": [critique.to_dict() for critique in self.critiques],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProposalBoard:
        proposals = data.get("proposals", [])
        critiques = data.get("critiques", [])
        selected = data.get("selected_id")
        return cls(
            cycle_number=int(data.get("cycle_number", 0)),
            selected_id=str(selected) if selected else None,
            proposals=[AgentProposal.from_dict(item) for item in proposals] if isinstance(proposals, list) else [],
            critiques=[ProposalCritique.from_dict(item) for item in critiques] if isinstance(critiques, list) else [],
        )


def proposal_artifact_path(state_dir: Path, cycle_number: int) -> Path:
    return state_dir / f"cycle-{cycle_number:04d}-proposals.json"


def proposal_markdown_path(state_dir: Path, cycle_number: int) -> Path:
    return state_dir / f"cycle-{cycle_number:04d}-proposals.md"


def parse_agent_proposal(role: str, text: str, *, index: int) -> AgentProposal:
    title = _field(text, "title") or _first_heading(text) or f"{role} proposal {index}"
    return AgentProposal(
        id=f"{role}-{index}",
        author_role=role,
        title=title,
        goal=_field(text, "goal") or _field(text, "mechanic") or "Create a meaningful game concept.",
        player_experience=_field(text, "player experience") or _field(text, "experience") or "",
        implementation_hint=_field(text, "implementation hint") or _field(text, "implementation") or "",
        acceptance=_field(text, "acceptance") or _field(text, "acceptance criteria") or "",
        supports=_normalize_supports(_field(text, "supports")),
        raw=text.strip(),
    )


def parse_proposal_critique(role: str, text: str) -> ProposalCritique:
    verdict = _field(text, "verdict") or ("BLOCK" if "BLOCK" in text.upper() else "BACKLOG")
    notes = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.lower().startswith("verdict:"):
            continue
        if stripped.startswith(("-", "*")):
            notes.append(stripped.lstrip("-* ").strip())
            continue
        if re.match(r"^\d+\.\s+", stripped):
            notes.append(re.sub(r"^\d+\.\s+", "", stripped))
            continue
        note_match = re.match(r"^<note\s+\d+>\s*(.+?)\s*</note>\s*$", stripped, flags=re.IGNORECASE)
        if note_match:
            notes.append(note_match.group(1).strip())
            continue
        note_open_match = re.match(r"^<note\s+\d+>\s*(.+)$", stripped, flags=re.IGNORECASE)
        if note_open_match:
            notes.append(note_open_match.group(1).strip())
    return ProposalCritique(author_role=role, verdict=verdict.upper(), notes=notes[:8], raw=text.strip())


def _critique_text(critique: ProposalCritique) -> str:
    if critique.notes:
        return " ".join(critique.notes)
    return critique.raw


def _critique_named_proposals(critique: ProposalCritique, proposals: list[AgentProposal]) -> set[str]:
    haystack = _critique_text(critique).lower()
    return {
        proposal.id
        for proposal in proposals
        if proposal.title.lower() in haystack or proposal.id.lower() in haystack
    }


def _critique_targets_proposal(
    critique: ProposalCritique,
    proposal: AgentProposal,
    proposals: list[AgentProposal],
) -> bool:
    if critique.verdict != "BLOCK":
        return False
    named = _critique_named_proposals(critique, proposals)
    if not named:
        return True
    return proposal.id in named


def choose_selected_proposal(proposals: list[AgentProposal], critique: ProposalCritique | None = None) -> str | None:
    if not proposals:
        return None
    if critique and critique.verdict == "BLOCK":
        named = _critique_named_proposals(critique, proposals)
        if named:
            for proposal in proposals:
                if proposal.supports or proposal.id in named:
                    continue
                if _is_substantive(proposal):
                    return proposal.id
    for proposal in proposals:
        if proposal.supports:
            continue
        if _is_substantive(proposal):
            return proposal.id
    for proposal in proposals:
        if _is_substantive(proposal):
            return proposal.id
    return proposals[0].id


def proposal_id_from_text(text: str, board: ProposalBoard | None) -> str | None:
    if board is None:
        return None
    proposal_ids = {proposal.id for proposal in board.proposals}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.lower().startswith("proposal:"):
            continue
        candidate = stripped.split(":", 1)[1].strip()
        return candidate if candidate in proposal_ids else None
    for proposal_id in proposal_ids:
        if proposal_id in text:
            return proposal_id
    return None


def with_selected_proposal(board: ProposalBoard, selected_id: str | None) -> ProposalBoard:
    if not selected_id:
        return board
    if not any(proposal.id == selected_id for proposal in board.proposals):
        return board
    return ProposalBoard(
        cycle_number=board.cycle_number,
        proposals=board.proposals,
        critiques=board.critiques,
        selected_id=selected_id,
    )


def validate_proposal_board(board: ProposalBoard | None) -> list[str]:
    if board is None:
        return []
    if not board.proposals:
        return ["Proposal board did not include any specialist proposals."]
    selected = board.selected_proposal()
    if selected is None:
        return ["Proposal board did not select a proposal to advance."]
    issues: list[str] = []
    proposal_ids = {proposal.id for proposal in board.proposals}
    for proposal in board.proposals:
        if proposal.supports and proposal.supports not in proposal_ids:
            issues.append(f"Supporting proposal {proposal.id} references missing proposal: {proposal.supports}")
    if selected.supports:
        issues.append(f"Selected proposal is support-only and cannot be advanced alone: {selected.id}")
    if not _is_substantive(selected):
        issues.append(f"Selected proposal is trivial or numeric-only: {selected.title}")
    for critique in board.critiques:
        if critique.verdict == "BLOCK" and _critique_targets_proposal(critique, selected, board.proposals):
            notes = "; ".join(critique.notes) if critique.notes else critique.raw
            issues.append(f"{critique.author_role} blocked the selected proposal: {notes}")
    return issues


def save_proposal_board(state_dir: Path, board: ProposalBoard) -> None:
    proposal_artifact_path(state_dir, board.cycle_number).write_text(json.dumps(board.to_dict(), indent=2) + "\n", encoding="utf-8")
    proposal_markdown_path(state_dir, board.cycle_number).write_text(render_proposal_board_markdown(board), encoding="utf-8")


def load_proposal_board(state_dir: Path, cycle_number: int) -> ProposalBoard | None:
    path = proposal_artifact_path(state_dir, cycle_number)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return ProposalBoard.from_dict(data) if isinstance(data, dict) else None


def render_proposal_board_markdown(board: ProposalBoard) -> str:
    lines = [f"# Cycle {board.cycle_number:04d} Proposal Board", ""]
    selected = board.selected_proposal()
    if selected:
        lines.extend(["## Selected Proposal", _proposal_summary(selected), ""])
        supporting = board.supporting_proposals()
        if supporting:
            lines.append("## Supporting Concepts")
            for proposal in supporting:
                lines.extend([_proposal_summary(proposal), ""])
    if board.proposals:
        lines.append("## Specialist Proposals")
        for proposal in board.proposals:
            lines.extend([_proposal_summary(proposal), ""])
    if board.critiques:
        lines.append("## Critiques")
        for critique in board.critiques:
            lines.append(f"### {critique.author_role}: {critique.verdict}")
            if critique.notes:
                lines.extend(f"- {note}" for note in critique.notes)
            else:
                lines.append(critique.raw)
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_proposal_context(board: ProposalBoard | None) -> str:
    if board is None or not board.proposals:
        return "No specialist proposal board is available for this cycle."
    selected = board.selected_proposal()
    parts = ["Specialist proposal board:"]
    if selected:
        parts.extend(["", "Selected concept to advance:", _proposal_summary(selected)])
        supporting = board.supporting_proposals()
        if supporting:
            parts.extend(["", "Supporting concepts for selected proposal:"])
            parts.extend(_proposal_summary(proposal) for proposal in supporting)
    parts.extend(["", "Available specialist proposals:"])
    parts.extend(_proposal_summary(proposal) for proposal in board.proposals)
    if board.critiques:
        parts.extend(["", "Pre-build critique:"])
        for critique in board.critiques:
            notes = "; ".join(critique.notes) if critique.notes else critique.raw
            parts.append(f"- {critique.author_role} {critique.verdict}: {notes}")
    return "\n".join(parts)


def _proposal_summary(proposal: AgentProposal) -> str:
    lines = [f"- [{proposal.id}] {proposal.title} ({proposal.author_role})", f"  Goal: {proposal.goal}"]
    if proposal.player_experience:
        lines.append(f"  Player experience: {proposal.player_experience}")
    if proposal.implementation_hint:
        lines.append(f"  Implementation hint: {proposal.implementation_hint}")
    if proposal.acceptance:
        lines.append(f"  Acceptance: {proposal.acceptance}")
    if proposal.supports:
        lines.append(f"  Supports: {proposal.supports}")
    return "\n".join(lines)


def _field(text: str, name: str) -> str:
    pattern = re.compile(rf"^\s*(?:[-*]\s*)?\**{re.escape(name)}\**\s*:\s*(.+)$", re.IGNORECASE | re.MULTILINE)
    match = pattern.search(text)
    return match.group(1).strip() if match else ""


def _first_heading(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip().lstrip("#").strip()
        if stripped:
            return stripped
    return ""


def _normalize_supports(value: str) -> str | None:
    cleaned = value.strip()
    if not cleaned or cleaned.lower() in {"none", "n/a", "na", "null", "-"}:
        return None
    return cleaned


def _is_substantive(proposal: AgentProposal) -> bool:
    text = f"{proposal.title} {proposal.goal} {proposal.player_experience}".lower()
    trivial_markers = ("hp from 10 to 15", "increase player starting hp", "turn counter")
    return not any(marker in text for marker in trivial_markers)
