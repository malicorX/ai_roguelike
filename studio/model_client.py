from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any, Callable

from studio.model_catalog import (
    NVIDIA_API_KEY_ENV_VARS,
    ModelEndpoint,
    failover_chain_for_role,
)

PostJson = Callable[[str, dict[str, Any], int], dict[str, Any]]
Sleep = Callable[[float], None]


class ModelRoutingError(RuntimeError):
    def __init__(self, role: str, attempts: list[str]) -> None:
        detail = "; ".join(attempts) if attempts else "no endpoints configured"
        super().__init__(f"All model endpoints failed for role {role!r}: {detail}")
        self.role = role
        self.attempts = attempts


def resolve_api_key(endpoint: ModelEndpoint) -> str | None:
    if endpoint.provider != "nvidia_nim":
        return None
    env_names = (endpoint.api_key_env,) if endpoint.api_key_env else NVIDIA_API_KEY_ENV_VARS
    for env_name in env_names:
        value = os.environ.get(env_name, "").strip()
        if value:
            return value
    return None


def is_rate_limit_error(exc: BaseException) -> bool:
    if isinstance(exc, urllib.error.HTTPError) and exc.code == 429:
        return True
    return _has_transient_marker(str(exc).lower(), _RATE_LIMIT_MARKERS)


def is_transient_model_error(exc: BaseException) -> bool:
    if isinstance(exc, TimeoutError):
        return True
    if isinstance(exc, urllib.error.URLError) and isinstance(getattr(exc, "reason", None), TimeoutError):
        return True
    message = str(exc).lower()
    return _has_transient_marker(message, _RATE_LIMIT_MARKERS) or _has_transient_marker(message, _TIMEOUT_MARKERS)


_RATE_LIMIT_MARKERS = (
    "429",
    "rate limit",
    "rate-limit",
    "too many requests",
    "quota exceeded",
    "usage limit",
    "limit exceeded",
    "out of limit",
    "throttl",
)

_TIMEOUT_MARKERS = (
    "timed out",
    "timeout",
    "time out",
    "deadline exceeded",
)


def _has_transient_marker(message: str, markers: tuple[str, ...]) -> bool:
    return any(marker in message for marker in markers)


def chat_with_failover(
    role: str,
    prompt: str,
    *,
    assigned_model: str | None,
    timeout_seconds: int,
    prefer_nvidia: bool = True,
    post_json: PostJson | None = None,
    sleep: Sleep | None = None,
) -> tuple[str, ModelEndpoint]:
    post = post_json or _post_json
    wait = sleep or time.sleep
    attempts: list[str] = []
    chain = failover_chain_for_role(role, assigned_model=assigned_model, prefer_nvidia=prefer_nvidia)

    for index, endpoint in enumerate(chain):
        if endpoint.provider == "nvidia_nim" and resolve_api_key(endpoint) is None:
            attempts.append(f"{endpoint.display_name()} skipped (missing NVIDIA API key)")
            continue
        try:
            content = _chat(endpoint, prompt, timeout_seconds=timeout_seconds, post_json=post)
            return content, endpoint
        except Exception as exc:  # noqa: BLE001 - routing inspects provider-specific failures
            attempts.append(f"{endpoint.display_name()} failed: {exc}")
            if is_transient_model_error(exc) and index + 1 < len(chain):
                retry_after = _retry_after_seconds(exc)
                if retry_after:
                    wait(min(retry_after, 5.0))
                continue
            if index + 1 < len(chain):
                continue
            raise ModelRoutingError(role, attempts) from exc

    raise ModelRoutingError(role, attempts)


def _chat(
    endpoint: ModelEndpoint,
    prompt: str,
    *,
    timeout_seconds: int,
    post_json: PostJson,
) -> str:
    if endpoint.provider == "ollama":
        payload = {
            "model": endpoint.model,
            "stream": False,
            "messages": [{"role": "user", "content": prompt}],
        }
        response = post_json(f"{endpoint.base_url}/api/chat", payload, timeout_seconds)
        message = response.get("message", {})
        content = message.get("content")
        if not isinstance(content, str):
            raise ValueError(f"Ollama response for {endpoint.model!r} did not include message.content")
        return content

    api_key = resolve_api_key(endpoint)
    if not api_key:
        raise RuntimeError("NVIDIA API key is not configured")
    payload = {
        "model": endpoint.model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "max_tokens": 8192,
    }
    response = post_json(
        f"{endpoint.base_url}/chat/completions",
        payload,
        timeout_seconds,
        headers={"Authorization": f"Bearer {api_key}"},
    )
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError(f"NVIDIA response for {endpoint.model!r} did not include choices")
    message = choices[0].get("message", {})
    content = message.get("content")
    if not isinstance(content, str):
        raise ValueError(f"NVIDIA response for {endpoint.model!r} did not include message.content")
    return content


def _retry_after_seconds(exc: BaseException) -> float | None:
    if isinstance(exc, urllib.error.HTTPError):
        retry_after = exc.headers.get("Retry-After")
        if retry_after:
            try:
                return float(retry_after)
            except ValueError:
                return None
    return None


def _post_json(
    url: str,
    payload: dict[str, Any],
    timeout_seconds: int,
    *,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    request_headers = {"Content-Type": "application/json"}
    if headers:
        request_headers.update(headers)
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=request_headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} from {url}: {body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Failed to call {url}: {exc}") from exc
