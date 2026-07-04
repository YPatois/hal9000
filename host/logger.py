"""File logger for the host daemon. Writes JSON-lines to ./logs/{category}/YYYY-MM-DD.log."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class FileLogger:
    def __init__(self, log_dir: Path) -> None:
        self.log_dir = log_dir

    def write(self, category: str, entry: dict[str, Any]) -> None:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        entry["timestamp"] = ts
        entry["category"] = category
        date_part = ts[:10]
        cat_dir = self.log_dir / category
        cat_dir.mkdir(parents=True, exist_ok=True)
        with open(cat_dir / f"{date_part}.log", "a") as f:
            f.write(json.dumps(entry, default=str) + "\n")
