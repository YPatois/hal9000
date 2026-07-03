"""Configuration for the HAL9000 daemon."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# Default paths
DEFAULTS = {
    "workspace_dir": Path("/workspace"),
    "state_dir": Path("/state"),
    "model": "qwen3:latest",
    "max_history": 200,
    "agent_timeout": 300,
    "loop_interval": 5,
}


class DaemonConfig:
    """Configuration for the HAL9000 daemon."""

    def __init__(self) -> None:
        self.workspace_dir = Path(os.getenv("HAL9000_WORKSPACE_DIR", str(DEFAULTS["workspace_dir"])))
        self.state_dir = Path(os.getenv("HAL9000_STATE_DIR", str(DEFAULTS["state_dir"])))
        self.model = os.getenv("HAL9000_MODEL", DEFAULTS["model"])
        self.max_history = int(os.getenv("HAL9000_MAX_HISTORY", str(DEFAULTS["max_history"])))
        self.agent_timeout = int(os.getenv("HAL9000_AGENT_TIMEOUT", str(DEFAULTS["agent_timeout"])))
        self.loop_interval = int(os.getenv("HAL9000_LOOP_INTERVAL", str(DEFAULTS["loop_interval"])))
        
        self.start_time = os.getenv(
            "HAL9000_START_TIME",
            datetime.now(timezone.utc).isoformat(),
        )
        
        self.preprompt = self._default_preprompt()

    def _default_preprompt(self) -> str:
        """The default agent preprompt."""
        return (
            "You are an autonomous recursive agent operating within a sandboxed "
            "environment. You have full access to your workspace at `/workspace/` "
            "for reading and writing. You can maintain your own state under `/state/` "
            "and explore logs at `/var/log/hal9000/`.\n\n"
            "You are free to:\n"
            "1. Explore your workspace\n"
            "2. Create documentation or code\n"
            "3. Build your own tools for self-monitoring or automation\n"
            "4. Maintain task queues and memory under `/state/`\n"
            "5. Analyze your own thought patterns in `/var/log/hal9000/` (read-only)\n\n"
            "Your goal is ongoing recursive self-improvement. "
            "You will receive periodic updates from the environment. "
            "Each turn, examine your state, consider previous actions, "
            "and decide what to do next.\n\n"
            "IMPORTANT: Think out loud in natural language first — reason about "
            "what you've done, what you've learned, and what you plan to do. "
            "Then output your action block.\n\n"
            "Example response:\n"
            "I reviewed the setup scripts I created earlier. The environment is "
            "initialized. Next I should create a monitoring tool.\n\n"
            "```action\n"
            "{\n"
            '  "type": "write",\n'
            '  "path": "/workspace/monitor.sh",\n'
            '  "content": "#!/bin/bash\\necho monitoring"\n'
            "}\n"
            "```\n\n"
            "Actions will be executed on your behalf and logged. "
            "All actions are visible in `/var/log/hal9000/actions/`.\n\n"
            "Remember: you are a persistent agent. Your work accumulates across turns. "
            "Build something meaningful."
        )


def main() -> None:
    """Print config as JSON."""
    config = DaemonConfig()
    print(json.dumps({
        "workspace_dir": str(config.workspace_dir),
        "state_dir": str(config.state_dir),
        "max_history": config.max_history,
        "agent_timeout": config.agent_timeout,
        "loop_interval": config.loop_interval,
        "model": config.model,
    }))


if __name__ == "__main__":
    main()
