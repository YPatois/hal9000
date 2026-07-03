"""Action executor for the HAL9000 daemon."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


class ActionExecutor:
    """Executes agent actions on the host. Agent cannot see this layer."""

    ALLOWED_PREFIXES = ("/workspace/", "/state/")

    def __init__(self, workspace_dir: Path, state_dir: Path = Path("/state")) -> None:
        self.workspace_dir = Path(workspace_dir)
        self.state_dir = Path(state_dir)

    def execute(self, action: dict[str, Any]) -> dict[str, Any]:
        action_type = action.get("type", "unknown")
        result = {"action": action_type, "success": False}

        try:
            if action_type == "write":
                result = self._write(action)
            else:
                result = {"error": f"Unknown action type: {action_type}"}
        except Exception as e:
            result["error"] = str(e)

        result["success"] = "error" not in result
        return result

    def execute_sync(self, action: dict[str, Any]) -> dict[str, Any]:
        return self.execute(action)

    def _write(self, action: dict[str, Any]) -> dict[str, Any]:
        path = action.get("path", "")
        content = action.get("content", "")

        if not any(path.startswith(p) for p in self.ALLOWED_PREFIXES):
            raise ValueError(f"Blocked: path must be under {self.ALLOWED_PREFIXES}: {path}")

        for prefix in self.ALLOWED_PREFIXES:
            if path.startswith(prefix):
                suffix = path.replace(prefix, "", 1)
                full_path = (Path(prefix.rstrip("/")) / suffix).resolve()
                if not any(str(full_path).startswith(p.rstrip("/")) for p in self.ALLOWED_PREFIXES):
                    raise ValueError(f"Blocked: resolved path {full_path} escapes allowed prefixes")
                break
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content)
        return {"path": str(full_path), "bytes_written": len(content)}


def main() -> None:
    """Run the executor as a standalone process for testing."""
    if sys.argv[1:]:
        action = json.loads(sys.argv[1])
    else:
        data = sys.stdin.read()
        action = json.loads(data) if data.strip() else {"type": "write", "path": "", "content": ""}

    executor = ActionExecutor(Path("/workspace"), Path("/state"))
    result = executor.execute(action)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
