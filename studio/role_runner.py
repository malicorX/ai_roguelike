from __future__ import annotations

from pathlib import Path
from typing import Any

from studio.config import StudioConfig, prefer_nvidia_models
from studio.model_client import chat_with_failover


def render_role_prompt(roles_dir: Path, role: str, context: str) -> str:
    role_path = roles_dir / f"{role}.md"
    role_prompt = role_path.read_text(encoding="utf-8")
    return f"{role_prompt.rstrip()}\n\n## Context\n\n{context.strip()}\n"


def build_ollama_payload(config: StudioConfig, role: str, prompt: str) -> dict[str, Any]:
    return {
        "model": config.model_for(role),
        "stream": False,
        "messages": [
            {
                "role": "user",
                "content": prompt,
            }
        ],
    }


def run_role(config: StudioConfig, roles_dir: Path, role: str, context: str, timeout_seconds: int = 120) -> str:
    prompt = render_role_prompt(roles_dir, role, context)
    assigned_model = config.model_assignments.get(role)
    content, endpoint = chat_with_failover(
        role,
        prompt,
        assigned_model=assigned_model,
        timeout_seconds=timeout_seconds,
        prefer_nvidia=prefer_nvidia_models(),
    )
    print(f"role {role}: served by {endpoint.display_name()}", flush=True)
    return content
