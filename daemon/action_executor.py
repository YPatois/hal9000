"""Action executor for the HAL9000 daemon."""
from __future__ import annotations

import httpx
import json
import sys
from pathlib import Path
from typing import Any


class ActionExecutor:
    """Executes agent actions on the host. Agent cannot see this layer."""

    def __init__(self, workspace_dir: Path) -> None:
        self.workspace_dir = Path(workspace_dir)

    def execute(self, action: dict[str, Any]) -> dict[str, Any]:
        """Execute an action. Returns result dict."""
        action_type = action.get("type", "unknown")
        result = {"action": action_type, "success": False}

        try:
            if action_type == "write":
                result = self._write(action)
            elif action_type == "http_request":
                result = self._http(action)
            else:
                result = {"error": f"Unknown action type: {action_type}"}
        except Exception as e:
            result["error"] = str(e)

        result["success"] = "error" not in result
        return result

    def execute_sync(self, action: dict[str, Any]) -> dict[str, Any]:
        """Sync version of execute for use with event loop."""
        return self.execute(action)

    def _write(self, action: dict[str, Any]) -> dict[str, Any]:
        """Write a file in the workspace."""
        path = action.get("path", "")
        content = action.get("content", "")

        if not path.startswith("/workspace/"):
            raise ValueError(f"Blocked: path must be under /workspace/: {path}")

        full_path = Path("/workspace") / path.replace("/workspace/", "")
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

    executor = ActionExecutor(Path("/workspace"))
    result = executor.execute(action)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
