from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from studio.config import StudioConfig


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
    payload = build_ollama_payload(config, role, prompt)
    base_url = config.ollama_base_url_for(role)
    response = _post_json(f"{base_url}/api/chat", payload, timeout_seconds=timeout_seconds)
    message = response.get("message", {})
    content = message.get("content")
    if not isinstance(content, str):
        raise ValueError(f"Ollama response for role {role!r} did not include message.content")
    return content


def _post_json(url: str, payload: dict[str, Any], timeout_seconds: int) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Failed to call Ollama at {url}: {exc}") from exc
