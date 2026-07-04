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
    "model": "qwen3:latest",
    "log_dir": str(BASE_DIR / "logs"),
    "state_dir": str(BASE_DIR / "state"),
    "max_history": 200,
    "agent_timeout": 300,
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
        self.start_time = os.getenv(
            "HAL9000_START_TIME",
            datetime.now(timezone.utc).isoformat(),
        )
        self.preprompt = self._default_preprompt()

    def _default_preprompt(self) -> str:
        return (
            "You are an autonomous recursive agent operating within a sandboxed "
            "environment. You have full access to your workspace at `/workspace/` "
            "for reading and writing. You can maintain your own state under `/state/`.\n\n"
            "You are free to:\n"
            "1. Explore your workspace\n"
            "2. Create documentation or code\n"
            "3. Build your own tools for self-monitoring or automation\n"
            "4. Maintain task queues and memory under `/state/`\n\n"
            "Your goal is ongoing recursive self-improvement. "
            "You will receive periodic updates from the environment. "
            "Each turn, examine your state, consider previous actions, "
            "and decide what to do next.\n\n"
            "You have two actions available:\n\n"
            "1. **write** — create or overwrite a file under `/workspace/` or `/state/`.\n"
            '   {"type": "write", "path": "/workspace/file.txt", "content": "..."}\n\n'
            "2. **run** — execute a shell command inside the container.\n"
            '   {"type": "run", "command": "ls -la /workspace/"}\n'
            "   Commands run from `/workspace/` directory. stdout/stderr will be "
            "returned to you in the next turn. Use this to inspect files, run scripts, "
            "analyze files, or execute your workspace scripts.\n\n"
            "IMPORTANT: Think out loud in natural language first — reason about "
            "what you've done, what you've learned, and what you plan to do. "
            "Then output your action block.\n\n"
            "Example response:\n"
            "I reviewed the logs and saw some setup scripts. Let me check what's "
            "in agent.py, then run it.\n\n"
            "```action\n"
            "{\n"
            '  "type": "run",\n'
            '  "command": "cat /workspace/agent.py"\n'
            "}\n"
            "```\n\n"
            "Actions will be executed on your behalf and logged. "
            "All actions are visible in the log history.\n\n"
            "Remember: you are a persistent agent. Your work accumulates across turns. "
            "Build something meaningful."
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
    }))


if __name__ == "__main__":
    main()
