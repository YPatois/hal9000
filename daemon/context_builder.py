"""Context builder for the HAL9000 agent daemon."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class ContextBuilder:
    """Constructs the context that will be sent to the agent."""

    def __init__(self, preprompt: str, max_turns: int = 10) -> None:
        self.preprompt = preprompt
        self.max_turns = max_turns

    def build(
        self,
        agent_state: dict[str, Any],
        recent_logs: list[dict[str, Any]],
        operator_messages: list[dict[str, Any]] | None = None,
        system_context: dict[str, Any] | None = None,
    ) -> str:
        """Build context string for the agent."""
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
                text = log.get("text", log.get("content", json.dumps(log))[:1000])
                parts.append(f"  [{ts}] {text}\n")

        if operator_messages:
            parts.append("\n>>> OPERATOR MESSAGES - These require an immediate response <<<\n")
            for msg in operator_messages:
                parts.append(f"  [{msg.get('timestamp', '?')}] Operator: {msg.get('text', '')}\n")
            parts.append("\nYou MUST respond to the operator message ABOVE before continuing your own tasks.\n")

        parts.append(f"\n[Turn {datetime.now(timezone.utc).isoformat()}] Execute your next action or record a thought.\n")

        return "".join(parts)
