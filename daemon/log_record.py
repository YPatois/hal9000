"""Log management for the HAL9000 daemon.
Logs are written to stdout (JSON-lines) and kept in an in-memory ring buffer.
No log files exist inside the container — the host captures stdout for persistence.
"""
from __future__ import annotations

import json
from collections import deque
from datetime import datetime, timezone
from typing import Any


class LogRecord:
    """Writes thought and action logs to stdout.
    Agent cannot modify these — they stream out of the container before
    the agent's action code even runs.
    """

    def __init__(self, max_history: int = 200) -> None:
        self._ring: deque[dict[str, Any]] = deque(maxlen=max_history)

    def write_entry(self, category: str, entry: dict[str, Any]) -> None:
        """Write an entry to stdout and keep in ring buffer."""
        entry["timestamp"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        entry["category"] = category
        self._ring.append(entry)
        # stdout is captured by host's docker logs → written to host files
        print(json.dumps(entry), flush=True)

    def recent_entries(self, n: int, categories: list[str] | None = None) -> list[dict[str, Any]]:
        """Return the last n entries from the ring buffer, optionally filtered by category."""
        if categories:
            filtered = [e for e in self._ring if e.get("category") in categories]
            return filtered[-n:]
        return list(self._ring)[-n:]

    def all_entries(self) -> list[dict[str, Any]]:
        """Return all entries in memory (for state persistence)."""
        return list(self._ring)

    def restore(self, entries: list[dict[str, Any]]) -> None:
        """Restore entries from saved state (e.g., after restart)."""
        for entry in entries:
            self._ring.append(entry)
