from __future__ import annotations

import argparse
import json
import re
import subprocess
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from studio.config import DEFAULT_MODEL
from studio.model_status import format_studio_routing_banner

ARTIFACT_FILES = ("director.md", "designer.md", "builder.md", "proposals.json", "report.json", "merge.json")
_INFERENCE_CALL_RE = re.compile(r"^role (\w+): calling ")
_INFERENCE_SERVED_RE = re.compile(r"^role (\w+): served by ")


def collect_watch_status(state_dir: Path, *, cycle_number: int | None = None) -> dict[str, object]:
    state_dir.mkdir(parents=True, exist_ok=True)
    cycle = cycle_number or _latest_cycle_number(state_dir)
    prefix = f"cycle-{cycle:04d}" if cycle else None
    orch = _orchestrator_process()

    artifacts: list[dict[str, object]] = []
    if prefix:
        for name in ARTIFACT_FILES:
            path = state_dir / f"{prefix}-{name}"
            artifacts.append({"name": name, "present": path.is_file()})

    run_log = state_dir / f"{prefix}-run.log" if prefix else None
    log_tail = _tail_lines(run_log, 24) if run_log and run_log.is_file() else []
    inference_log = state_dir / "inference.log"
    inference_recent = _tail_lines(inference_log, 8) if inference_log.is_file() else []

    routing = _routing_from_process(orch)
    if not routing.get("banner"):
        routing["banner"] = format_studio_routing_banner(
            _config_from_assignments(str(routing.get("model_assignments") or "")),
            evaluation_target=str(routing.get("evaluation_target") or "sparky2"),
        )

    activity = _activity_snapshot(
        state_dir,
        run_log,
        log_tail,
        inference_recent,
        orch,
        artifacts,
    )

    return {
        "updated_at": datetime.now(UTC).isoformat(),
        "cycle_number": cycle,
        "studio_host": "sparky1",
        "evaluation_host": "sparky2",
        "orchestrator": orch,
        "routing": routing,
        "activity": activity,
        "artifacts": artifacts,
        "log_tail": log_tail,
        "inference_recent": inference_recent,
        "devlog_url": f"https://www.theebie.de/sites/roguelike/devlog/cycle-{cycle:04d}.html" if cycle else None,
        "play_url": "https://www.theebie.de/sites/roguelike/",
    }


def _latest_cycle_number(state_dir: Path) -> int:
    numbers: list[int] = []
    for path in state_dir.glob("cycle-*-run.log"):
        match = re.match(r"cycle-(\d+)-run\.log$", path.name)
        if match:
            numbers.append(int(match.group(1)))
    return max(numbers) if numbers else 0


def _tail_lines(path: Path, count: int) -> list[str]:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return lines[-count:]


def _orchestrator_process() -> dict[str, object]:
    try:
        result = subprocess.run(
            ["pgrep", "-af", "python3 -u -m studio.orchestrator"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return {"running": False}
    line = next((row for row in result.stdout.splitlines() if "python3 -u -m studio.orchestrator" in row), "")
    if not line:
        return {"running": False}
    pid_text = line.split(None, 1)[0]
    pid = int(pid_text) if pid_text.isdigit() else None
    elapsed = _process_elapsed(pid) if pid else None
    stat = _process_stat(pid) if pid else None
    models = _extract_flag_value(line, "--models")
    evaluation_target = _extract_flag_value(line, "--evaluation-target") or "sparky2"
    prefer_nvidia = _process_env(pid, "STUDIO_PREFER_NVIDIA") if pid else None
    role_timeout = _extract_flag_value(line, "--role-timeout-seconds")
    return {
        "running": True,
        "pid": pid,
        "elapsed": elapsed,
        "state": stat,
        "model_assignments": models,
        "evaluation_target": evaluation_target,
        "prefer_nvidia": prefer_nvidia,
        "role_timeout_seconds": int(role_timeout) if role_timeout and role_timeout.isdigit() else 900,
        "until_green": "--until-green" in line,
        "apply_writes": "--apply-writes" in line,
    }


def _process_env(pid: int, key: str) -> str | None:
    environ_path = Path(f"/proc/{pid}/environ")
    if not environ_path.is_file():
        return None
    for entry in environ_path.read_bytes().split(b"\0"):
        if entry.startswith(key.encode() + b"="):
            return entry.decode("utf-8", errors="replace").split("=", 1)[1]
    return None


def _process_elapsed(pid: int) -> str | None:
    result = subprocess.run(
        ["ps", "-p", str(pid), "-o", "etime="],
        capture_output=True,
        text=True,
        check=False,
    )
    value = result.stdout.strip()
    return value or None


def _process_stat(pid: int) -> str | None:
    result = subprocess.run(
        ["ps", "-p", str(pid), "-o", "stat="],
        capture_output=True,
        text=True,
        check=False,
    )
    value = result.stdout.strip()
    return value or None


def _extract_flag_value(command_line: str, flag: str) -> str | None:
    match = re.search(rf"{re.escape(flag)} '([^']*)'", command_line)
    if match:
        return match.group(1)
    match = re.search(rf"{re.escape(flag)} (\S+)", command_line)
    if match:
        return match.group(1)
    return None


def _activity_snapshot(
    state_dir: Path,
    run_log: Path | None,
    log_tail: list[str],
    inference_recent: list[str],
    orch: dict[str, object],
    artifacts: list[dict[str, object]],
) -> dict[str, object]:
    step = _latest_step(log_tail)
    phase = _phase_from_step(step)
    role_timeout = int(orch.get("role_timeout_seconds") or 900)
    inference = _inference_state(inference_recent)
    step_age_seconds = _path_age_seconds(run_log) if run_log and run_log.is_file() else None
    inference_age_seconds = _path_age_seconds(state_dir / "inference.log")
    ollama_models = _ollama_loaded_models()
    ollama_busy = bool(ollama_models)
    cycle_outcome = _cycle_outcome(artifacts, log_tail, orch)
    health, message = _activity_health(
        phase=phase,
        step=step,
        step_age_seconds=step_age_seconds,
        role_timeout_seconds=role_timeout,
        inference_pending=bool(inference.get("pending")),
        pending_role=str(inference.get("pending_role") or ""),
        ollama_busy=ollama_busy,
        ollama_models=ollama_models,
    )
    if not orch.get("running"):
        if cycle_outcome == "merged":
            health, message = "done", "Cycle merged — deploy/devlog step complete"
        elif cycle_outcome == "passed":
            health, message = "done", "Cycle passed evaluation — orchestrator idle"
        elif cycle_outcome == "blocked" and health == "idle":
            health, message = "blocked", "Cycle blocked — until-green will retry on next run"
    pipeline = _pipeline_hint(phase, orch)
    ui_mood = _ui_mood(health=health, running=bool(orch.get("running")), cycle_outcome=cycle_outcome)
    return {
        "phase": phase,
        "step": step or None,
        "health": health,
        "message": message,
        "pipeline": pipeline,
        "ui_mood": ui_mood,
        "cycle_outcome": cycle_outcome,
        "step_age_seconds": step_age_seconds,
        "inference_age_seconds": inference_age_seconds,
        "role_timeout_seconds": role_timeout,
        "inference_pending": bool(inference.get("pending")),
        "pending_role": inference.get("pending_role"),
        "ollama_loaded": ollama_models,
        "deploy_phase": phase == "deploy",
    }


def _cycle_outcome(
    artifacts: list[dict[str, object]],
    log_tail: list[str],
    orch: dict[str, object],
) -> str | None:
    if orch.get("running"):
        return None
    present = {str(item["name"]): bool(item["present"]) for item in artifacts}
    tail_text = " ".join(log_tail[-8:]).lower()
    tail_compact = tail_text.replace(" ", "")
    if present.get("merge.json"):
        return "merged"
    if "blocked=false" in tail_compact:
        return "passed"
    if "blocked at" in tail_text or "blocked=true" in tail_compact:
        return "blocked"
    return None


def _ui_mood(*, health: str, running: bool, cycle_outcome: str | None) -> str:
    if health == "done" or cycle_outcome in {"merged", "passed"}:
        return "done"
    if health in {"stale", "blocked"}:
        return "broken"
    if health in {"warning", "retry"}:
        return "slow"
    if running:
        return "working"
    return "idle"


def _latest_step(log_tail: list[str]) -> str:
    for line in reversed(log_tail):
        text = line.strip()
        if text:
            return text
    return ""


def _phase_from_step(step: str) -> str:
    lower = step.lower()
    if "blocked" in lower:
        return "blocked"
    if "until-green retry" in lower:
        return "retry"
    if "running sparky2 evaluation" in lower:
        return "evaluation"
    if "entering write path" in lower:
        return "write"
    if "running reviewer" in lower:
        return "reviewer"
    if "running builder" in lower:
        return "builder"
    if "running designer" in lower:
        return "designer"
    if "running director" in lower or "proposal specialist" in lower:
        return "director"
    if "running proposal" in lower:
        return "proposals"
    if "published devlog" in lower or "deployed" in lower:
        return "deploy"
    if "cycle started" in lower:
        return "cycle"
    return "unknown"


def _inference_state(lines: list[str]) -> dict[str, object]:
    pending_role: str | None = None
    for line in reversed(lines):
        served = _INFERENCE_SERVED_RE.match(line.strip())
        if served:
            return {"pending": False, "pending_role": None, "last_role": served.group(1)}
        calling = _INFERENCE_CALL_RE.match(line.strip())
        if calling:
            pending_role = calling.group(1)
            break
    if pending_role:
        return {"pending": True, "pending_role": pending_role, "last_role": pending_role}
    return {"pending": False, "pending_role": None, "last_role": None}


def _activity_health(
    *,
    phase: str,
    step: str,
    step_age_seconds: float | None,
    role_timeout_seconds: int,
    inference_pending: bool,
    pending_role: str,
    ollama_busy: bool,
    ollama_models: list[str],
) -> tuple[str, str]:
    age = step_age_seconds or 0.0
    age_text = _format_duration(age)

    if phase == "blocked":
        return "blocked", "Cycle blocked — until-green will retry from the failed stage"
    if phase == "retry":
        return "retry", "Preparing until-green retry"
    if inference_pending:
        model_hint = ", ".join(ollama_models) if ollama_models else "no model loaded in Ollama"
        if age > role_timeout_seconds:
            return (
                "stale",
                f"{pending_role or 'role'} likely timed out ({age_text} > {role_timeout_seconds}s limit)",
            )
        if age > role_timeout_seconds * 0.75:
            return (
                "warning",
                f"Waiting for {pending_role or 'model'} ({age_text} / {role_timeout_seconds}s) · {model_hint}",
            )
        if ollama_busy:
            return (
                "ok",
                f"{pending_role or 'role'} generating on Ollama ({age_text} elapsed) · {model_hint}",
            )
        return (
            "warning",
            f"Called {pending_role or 'model'} but Ollama idle ({age_text}) — may be queueing",
        )
    if phase in {"evaluation", "write", "deploy"}:
        return "ok", f"In {phase} phase ({age_text} on current step)"
    if phase in {"builder", "director", "designer", "reviewer", "proposals"}:
        return "ok", f"Processing {phase} locally ({age_text} on current step)"
    if step:
        return "idle", f"Last step: {step}"
    return "idle", "Waiting for cycle activity"


def _pipeline_hint(phase: str, orch: dict[str, object]) -> str:
    deploy = "merge + deploy" if orch.get("apply_writes") else "merge only"
    order = f"proposals → director → designer → builder → reviewer → sparky2 eval → {deploy}"
    if phase == "deploy":
        return "Deploy runs at the end after green evaluation and merge"
    if phase in {"builder", "director", "designer", "reviewer", "proposals", "retry", "blocked"}:
        return f"Still in sparky1 studio — deploy is later. Pipeline: {order}"
    if phase == "evaluation":
        return "sparky2 running npm gates; deploy follows only if evaluation passes and merge succeeds"
    if phase == "write":
        return f"Applying branch and merging — {deploy} next if green"
    return order


def _path_age_seconds(path: Path) -> float | None:
    if not path.is_file():
        return None
    return max(0.0, datetime.now().timestamp() - path.stat().st_mtime)


def _format_duration(seconds: float) -> str:
    total = int(seconds)
    minutes, secs = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def _ollama_loaded_models() -> list[str]:
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/ps", timeout=2) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return []
    names: list[str] = []
    for entry in payload.get("models", []):
        name = str(entry.get("name") or entry.get("model") or "")
        if name.startswith("hf.co/InternScience/"):
            names.append("Agents-A1")
        elif name:
            names.append(name.split(":")[0])
    return names


def _routing_from_process(orch: dict[str, object]) -> dict[str, object]:
    assignments = str(orch.get("model_assignments") or "")
    evaluation_target = str(orch.get("evaluation_target") or "sparky2")
    prefer_env = str(orch.get("prefer_nvidia") or "").lower()
    if prefer_env in {"nvidia-first", "1", "true", "yes", "nvidia"}:
        mode = "nvidia-first"
    elif prefer_env in {"local-only", "0", "false", "no", "local"}:
        mode = "local-only"
    elif assignments and "nvidia:" not in assignments and "hf.co/InternScience" in assignments:
        mode = "local-only"
    elif orch.get("running"):
        mode = "custom"
    else:
        mode = "local-only"

    unique_models = sorted({part.split("=", 1)[1] for part in assignments.split(",") if "=" in part})
    if not unique_models:
        unique_models = [DEFAULT_MODEL]

    return {
        "mode": mode,
        "inference_backend": "sparky1 Ollama :11434" if mode == "local-only" else "mixed",
        "evaluation_target": evaluation_target,
        "assigned_models": unique_models,
        "model_assignments": assignments or None,
        "banner": None,
    }


def _config_from_assignments(assignments: str):
    from studio.config import StudioConfig

    if assignments.strip():
        return StudioConfig.from_model_string(assignments)
    return StudioConfig()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Emit ai_roguelike studio watch status as JSON.")
    parser.add_argument("--state-dir", type=Path, default=Path("studio/state"))
    parser.add_argument("--cycle", type=int, default=0)
    args = parser.parse_args(argv)
    cycle_number = args.cycle if args.cycle > 0 else None
    payload = collect_watch_status(args.state_dir, cycle_number=cycle_number)
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
