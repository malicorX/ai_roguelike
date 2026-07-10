from __future__ import annotations

import os
from dataclasses import dataclass, field, replace

DEFAULT_MODEL = "hf.co/InternScience/Agents-A1-Q4_K_M-GGUF:latest"
SPARKY1_OLLAMA_BASE_URL = "http://127.0.0.1:11434"
# sparky2 runs npm gates only; all Ollama inference uses sparky1 (other projects own sparky2 :11435).
SPARKY1_OLLAMA_REMOTE_URL = "http://sparky1:11434"
SPARKY2_OLLAMA_BASE_URL = SPARKY1_OLLAMA_REMOTE_URL

EVALUATION_ROLES = frozenset({"art_director", "player", "tester", "visual_qa"})


@dataclass(frozen=True)
class StudioConfig:
    model_assignments: dict[str, str] = field(default_factory=dict)
    developer_base_url: str = SPARKY1_OLLAMA_BASE_URL
    evaluator_base_url: str = SPARKY2_OLLAMA_BASE_URL

    @classmethod
    def from_model_string(cls, models: str) -> StudioConfig:
        return cls(model_assignments=parse_model_assignments(models))

    @classmethod
    def for_evaluation(cls, models: str, *, base_url: str | None = None) -> StudioConfig:
        import os

        return cls(
            model_assignments=parse_model_assignments(models),
            evaluator_base_url=base_url or os.environ.get("EVAL_OLLAMA_URL", SPARKY1_OLLAMA_REMOTE_URL),
        )

    def model_for(self, role: str) -> str:
        return self.model_assignments.get(role, DEFAULT_MODEL)

    def ollama_base_url_for(self, role: str) -> str:
        if role in EVALUATION_ROLES:
            return self.evaluator_base_url
        return self.developer_base_url

    def with_role_model(self, role: str, model: str) -> StudioConfig:
        assignments = dict(self.model_assignments)
        assignments[role] = model
        return replace(self, model_assignments=assignments)


def parse_model_assignments(raw: str) -> dict[str, str]:
    if not raw.strip():
        return {}

    assignments: dict[str, str] = {}
    for entry in raw.split(","):
        if "=" not in entry:
            raise ValueError(f"Malformed model assignment: {entry!r}")
        role, model = (part.strip() for part in entry.split("=", 1))
        if not role or not model:
            raise ValueError(f"Malformed model assignment: {entry!r}")
        assignments[role] = model
    return assignments


def evaluation_models_string(config: StudioConfig) -> str:
    return ",".join(
        f"{role}={config.model_assignments[role]}"
        for role in sorted(config.model_assignments)
        if role in EVALUATION_ROLES
    )


def prefer_nvidia_models() -> bool:
    raw = os.environ.get("STUDIO_PREFER_NVIDIA", "auto").strip().lower()
    if raw in {"0", "false", "no", "local", "local-only"}:
        return False
    if raw in {"1", "true", "yes", "nvidia", "nvidia-first"}:
        return True
    # auto: local by default; cloud only when explicitly requested via env
    return False
