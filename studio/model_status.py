from __future__ import annotations

from studio.config import DEFAULT_MODEL, EVALUATION_ROLES, StudioConfig, prefer_nvidia_models
from studio.model_catalog import endpoint_for_assignment


def role_host(role: str) -> str:
    if role in EVALUATION_ROLES:
        return "sparky2 (eval) → sparky1 (model)"
    return "sparky1"


def format_role_route(config: StudioConfig, role: str) -> str:
    assigned = config.model_assignments.get(role)
    endpoint = endpoint_for_assignment(assigned or DEFAULT_MODEL, role=role)
    if endpoint.provider == "nvidia_nim":
        backend = "build.nvidia.com"
        host = role_host(role)
    elif role in EVALUATION_ROLES:
        backend = "sparky1:11434"
        host = "sparky2 eval → sparky1"
    else:
        backend = "sparky1:11434"
        host = "sparky1"
    model = endpoint.model
    if model.startswith("hf.co/"):
        short = "Agents-A1"
    elif "/" in model:
        short = model.split("/", 1)[1]
    else:
        short = model
    return f"{host} · {backend} · {short}"


def format_studio_routing_banner(config: StudioConfig, *, evaluation_target: str) -> str:
    mode = "local-only" if not prefer_nvidia_models() else "nvidia-first"
    models = sorted(set(config.model_assignments.values())) if config.model_assignments else [DEFAULT_MODEL]
    if len(models) == 1:
        model_line = f"model={_short_model_name(models[0])}"
    else:
        model_line = f"{len(models)} role-specific models"
    return (
        f"studio routing: agents on sparky1 Ollama :11434 · evaluation gates on {evaluation_target} · "
        f"eval LLM roles call sparky1 (not sparky2) · {mode} · {model_line}"
    )


def print_studio_routing_banner(config: StudioConfig, *, evaluation_target: str) -> None:
    print(format_studio_routing_banner(config, evaluation_target=evaluation_target), flush=True)


def _short_model_name(model: str) -> str:
    if model.startswith("hf.co/"):
        return "Agents-A1"
    if model.startswith("nvidia:"):
        return model.removeprefix("nvidia:")
    return model
