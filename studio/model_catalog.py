from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from studio.config import (
    DEFAULT_MODEL,
    EVALUATION_ROLES,
    SPARKY1_OLLAMA_BASE_URL,
    SPARKY1_OLLAMA_REMOTE_URL,
)

ModelProvider = Literal["ollama", "nvidia_nim"]

NVIDIA_NIM_BASE_URL = "https://integrate.api.nvidia.com/v1"
NVIDIA_API_KEY_ENV_VARS = ("NVIDIA_API_KEY", "NVAPI_KEY")


@dataclass(frozen=True)
class ModelEndpoint:
    provider: ModelProvider
    model: str
    base_url: str
    api_key_env: str | None = None
    label: str = ""

    def display_name(self) -> str:
        return self.label or f"{self.provider}:{self.model}"


def _nvidia(model: str, *, label: str = "") -> ModelEndpoint:
    return ModelEndpoint(
        provider="nvidia_nim",
        model=model,
        base_url=NVIDIA_NIM_BASE_URL,
        api_key_env=NVIDIA_API_KEY_ENV_VARS[0],
        label=label,
    )


def _ollama(model: str, base_url: str, *, label: str = "") -> ModelEndpoint:
    return ModelEndpoint(
        provider="ollama",
        model=model,
        base_url=base_url,
        label=label,
    )


# Curated for studio work: instruction following, structured critique, code patches.
# NVIDIA models are tried in order when rate-limited on build.nvidia.com.
NVIDIA_STUDIO_CHAIN: tuple[ModelEndpoint, ...] = (
    _nvidia("nvidia/nemotron-3-nano-30b-a3b", label="Nemotron 3 Nano 30B"),
    _nvidia("meta/llama-3.3-70b-instruct", label="Llama 3.3 70B"),
    _nvidia("mistralai/mistral-nemotron", label="Mistral Nemotron"),
    _nvidia("meta/llama-3.1-70b-instruct", label="Llama 3.1 70B"),
    _nvidia("meta/llama-3.1-8b-instruct", label="Llama 3.1 8B"),
    _nvidia("nvidia/llama-3.1-nemotron-nano-8b-v1", label="Nemotron Nano 8B"),
)

LOCAL_DEVELOPER_CHAIN: tuple[ModelEndpoint, ...] = (
    _ollama(DEFAULT_MODEL, SPARKY1_OLLAMA_BASE_URL, label="Agents-A1 local"),
    _ollama("qwen3:14b", SPARKY1_OLLAMA_BASE_URL, label="Qwen3 14B local"),
    _ollama("llama3.1:8b", SPARKY1_OLLAMA_BASE_URL, label="Llama 3.1 8B local"),
    _ollama("gemma4:12b", SPARKY1_OLLAMA_BASE_URL, label="Gemma4 12B local"),
)

LOCAL_EVALUATOR_CHAIN: tuple[ModelEndpoint, ...] = (
    _ollama(DEFAULT_MODEL, SPARKY1_OLLAMA_REMOTE_URL, label="Agents-A1 via sparky1"),
    _ollama("qwen3:14b", SPARKY1_OLLAMA_REMOTE_URL, label="Qwen3 14B via sparky1"),
    _ollama("llama3.1:8b", SPARKY1_OLLAMA_REMOTE_URL, label="Llama 3.1 8B via sparky1"),
)


def is_nvidia_model_id(model: str) -> bool:
    normalized = model.strip()
    if not normalized or normalized.startswith("hf.co/"):
        return False
    if normalized.startswith("ollama:") or normalized.startswith("nvidia:"):
        return normalized.startswith("nvidia:")
    return "/" in normalized


def endpoint_for_assignment(model: str, *, role: str) -> ModelEndpoint:
    base_url = (
        SPARKY1_OLLAMA_REMOTE_URL
        if role in EVALUATION_ROLES
        else SPARKY1_OLLAMA_BASE_URL
    )
    normalized = model.strip()
    if normalized.startswith("nvidia:"):
        return _nvidia(normalized.removeprefix("nvidia:"))
    if normalized.startswith("ollama:"):
        payload = normalized.removeprefix("ollama:")
        return _ollama(payload, base_url)
    if is_nvidia_model_id(normalized):
        return _nvidia(normalized)
    return _ollama(normalized, base_url)


def failover_chain_for_role(
    role: str,
    *,
    assigned_model: str | None = None,
    prefer_nvidia: bool = True,
) -> tuple[ModelEndpoint, ...]:
    local_chain = LOCAL_EVALUATOR_CHAIN if role in EVALUATION_ROLES else LOCAL_DEVELOPER_CHAIN
    chains: list[tuple[ModelEndpoint, ...]] = []
    if assigned_model:
        chains.append((endpoint_for_assignment(assigned_model, role=role),))
    if prefer_nvidia:
        chains.append(NVIDIA_STUDIO_CHAIN)
    chains.append(local_chain)
    return _dedupe_endpoints(*chains)


def _dedupe_endpoints(*groups: tuple[ModelEndpoint, ...]) -> tuple[ModelEndpoint, ...]:
    seen: set[tuple[ModelProvider, str, str]] = set()
    ordered: list[ModelEndpoint] = []
    for group in groups:
        for endpoint in group:
            key = (endpoint.provider, endpoint.model, endpoint.base_url)
            if key in seen:
                continue
            seen.add(key)
            ordered.append(endpoint)
    return tuple(ordered)
