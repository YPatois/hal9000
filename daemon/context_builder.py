"""Context builder for the HAL9000 agent daemon."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class DescriptionDocLoader:
    """Loads markdown docs from a description directory.
    Used by the host daemon to inject docs into the system message."""

    def __init__(self, desc_dir: str | Path) -> None:
        self.desc_dir = Path(desc_dir)

    def load_all(self) -> str:
        if not self.desc_dir.is_dir():
            return ""
        parts: list[str] = []
        for f in sorted(self.desc_dir.glob("*.md"), key=lambda p: p.name):
            try:
                parts.append(f.read_text().strip())
            except OSError:
                pass
        return "\n\n".join(parts)

    def load(self, name: str) -> str:
        path = self.desc_dir / name
        if not path.name.endswith(".md"):
            path = path.with_suffix(".md")
        if path.is_file():
            try:
                return path.read_text().strip()
            except OSError:
                pass
        return ""


class ContextBuilder:
    """Constructs the context string sent to the agent."""

    def __init__(self, preprompt: str, max_turns: int = 15) -> None:
        self.preprompt = preprompt
        self.max_turns = max_turns
        self.max_log_chars = 4000

    def build(
        self,
        agent_state: dict[str, Any],
        recent_logs: list[dict[str, Any]],
        operator_messages: list[dict[str, Any]] | None = None,
        system_context: dict[str, Any] | None = None,
    ) -> str:
        parts = [self.preprompt, "\n"]

        if system_context:
            parts.append("[System Context]")
            for key, value in system_context.items():
                label = key.replace("_", " ").title()
                parts.append(f"  {label}: {value}")
            parts.append("\n")

        if agent_state.get("last_summary"):
            parts.append(f"[Agent State] {agent_state['last_summary']}\n")

        if recent_logs:
            parts.append("[Log History]\n")
            for log in recent_logs[-self.max_turns:]:
                ts = log.get("timestamp", log.get("ts", "?"))
                text = log.get("text", log.get("content", json.dumps(log))[:self.max_log_chars])
                parts.append(f"  [{ts}] {text}\n")

        if operator_messages:
            parts.append("\n>>> OPERATOR MESSAGES <<<\n")
            for msg in operator_messages:
                parts.append(f"  [{msg.get('timestamp', '?')}] Operator: {msg.get('text', '')}\n")
            parts.append(
                "You MUST respond to the operator message ABOVE before continuing.\n"
            )

        parts.append(
            f"\n[Turn {datetime.now(timezone.utc).isoformat()}] "
            "Execute your next action or record a thought.\n"
        )

        return "".join(parts)
