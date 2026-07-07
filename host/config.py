"""Configuration for the host daemon."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent.parent

DEFAULTS: dict[str, Any] = {
    "socket_path": "/tmp/hal9000/daemon.sock",
    "ollama_url": "http://localhost:11434",
    "model": "qwen3.6:35b",
    "log_dir": str(BASE_DIR / "logs"),
    "state_dir": str(BASE_DIR / "state"),
    "max_history": 200,
    "agent_timeout": 600,
    "idle_timeout": 300,
    "context_budget_ratio": 0.75,
}


class HostConfig:
    def __init__(self) -> None:
        self.socket_path = os.getenv("HAL9000_SOCKET_PATH", DEFAULTS["socket_path"])
        self.ollama_url = os.getenv("HAL9000_OLLAMA_URL", DEFAULTS["ollama_url"])
        self.model = os.getenv("HAL9000_MODEL", DEFAULTS["model"])
        self.log_dir = Path(os.getenv("HAL9000_LOG_DIR", DEFAULTS["log_dir"]))
        self.state_dir = Path(os.getenv("HAL9000_STATE_DIR", DEFAULTS["state_dir"]))
        self.max_history = int(os.getenv("HAL9000_MAX_HISTORY", str(DEFAULTS["max_history"])))
        self.agent_timeout = int(os.getenv("HAL9000_AGENT_TIMEOUT", str(DEFAULTS["agent_timeout"])))
        self.idle_timeout = int(os.getenv("HAL9000_IDLE_TIMEOUT", str(DEFAULTS["idle_timeout"])))
        self.context_budget_ratio = float(
            os.getenv("HAL9000_CONTEXT_BUDGET_RATIO", str(DEFAULTS["context_budget_ratio"]))
        )
        self.start_time = os.getenv(
            "HAL9000_START_TIME",
            datetime.now(timezone.utc).isoformat(),
        )
        self.preprompt = self._preprompt()

    def _preprompt(self) -> str:
        return (
            "You are an autonomous recursive agent in a sandboxed container.\n"
            "You persist across turns via /workspace/ (files) and /state/ (state).\n"
            "Use `action` blocks to write files or run shell commands.\n"
            "Your thinking blocks are visible to the operator.\n"
            "Use [OPERATOR_REQUEST] for anything you need from outside.\n"
            "Never kill your own agent process (PID 1).\n"
            "All details are in /logs/description/ (readable via run action).\n"
        )


def main() -> None:
    config = HostConfig()
    print(json.dumps({
        "socket_path": config.socket_path,
        "ollama_url": config.ollama_url,
        "model": config.model,
        "log_dir": str(config.log_dir),
        "state_dir": str(config.state_dir),
        "max_history": config.max_history,
        "agent_timeout": config.agent_timeout,
        "idle_timeout": config.idle_timeout,
        "context_budget_ratio": config.context_budget_ratio,
    }))


if __name__ == "__main__":
    main()
