from __future__ import annotations

import os
from dataclasses import dataclass, field

DEFAULT_MODEL = "hf.co/InternScience/Agents-A1-Q4_K_M-GGUF:latest"
SPARKY1_OLLAMA_BASE_URL = "http://127.0.0.1:11434"
SPARKY2_OLLAMA_BASE_URL = "http://sparky2:11435"

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
            evaluator_base_url=base_url or os.environ.get("EVAL_OLLAMA_URL", "http://127.0.0.1:11435"),
        )

    def model_for(self, role: str) -> str:
        return self.model_assignments.get(role, DEFAULT_MODEL)

    def ollama_base_url_for(self, role: str) -> str:
        if role in EVALUATION_ROLES:
            return self.evaluator_base_url
        return self.developer_base_url


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
    return any(os.environ.get(name, "").strip() for name in ("NVIDIA_API_KEY", "NVAPI_KEY"))
