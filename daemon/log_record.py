"""Log management for the HAL9000 daemon."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


class LogRecord:
    """Writes thought and action logs. Agent cannot access these files."""

    def __init__(self, log_dir: Path) -> None:
        self.log_dir = Path(log_dir)
        (self.log_dir / "thoughts").mkdir(parents=True, exist_ok=True)
        (self.log_dir / "actions").mkdir(parents=True, exist_ok=True)
        (self.log_dir / "updates").mkdir(parents=True, exist_ok=True)

    def _get_file(self, category: str, date: str) -> Path:
        return self.log_dir / category / f"{date}.log"

    def write_entry(self, category: str, entry: dict[str, Any]) -> str:
        """Write an entry to a log category. Returns the file path."""
        entry["timestamp"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        date = entry["timestamp"][:10]
        filepath = self._get_file(category, date)
        (filepath).parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, "a") as f:
            f.write(json.dumps(entry) + "\n")
        return str(filepath)

    def recent_entries(self, n: int, categories: list[str]) -> list[dict[str, Any]]:
        """Read the last n entries from the given categories."""
        all_entries = []
        for cat in categories:
            cat_dir = self.log_dir / cat
            if not cat_dir.exists():
                continue
            for log_file in sorted(cat_dir.glob("*.log")):
                with open(log_file) as f:
                    for line in f:
                        if line.strip():
                            all_entries.append(json.loads(line))
                if len(all_entries) >= n * 2:
                    break
        return all_entries[-n:] or [{"type": "system", "text": "Initial environment. You have full access to /workspace/ sandbox. You are free to think, explore, and create."}]
