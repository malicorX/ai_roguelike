from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from studio.config import StudioConfig, prefer_nvidia_models
from studio.model_client import chat_with_failover
from studio.model_status import format_role_route


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
    route = format_role_route(config, role)
    calling = f"role {role}: calling {route}"
    print(calling, flush=True)
    _append_inference_log(calling)
    content, endpoint = chat_with_failover(
        role,
        prompt,
        assigned_model=assigned_model,
        timeout_seconds=timeout_seconds,
        prefer_nvidia=prefer_nvidia_models(),
    )
    line = f"role {role}: served by {endpoint.display_name()}"
    print(line, flush=True)
    _append_inference_log(line)
    return content


def _append_inference_log(message: str) -> None:
    state_dir = os.environ.get("STUDIO_STATE_DIR", "").strip()
    if not state_dir:
        return
    log_path = Path(state_dir) / "inference.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(message.rstrip() + "\n")
