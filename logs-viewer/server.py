"""Simple HTTP server for the HAL9000 log viewer.
Serves index.html and provides API endpoints for logs, workspace, and state.
"""
from __future__ import annotations

import http.server
import json
import os
import socket
import sys
from pathlib import Path
from typing import Any

# Resolve project root (two levels up from this file)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
INDEX_PATH = PROJECT_ROOT / "logs-viewer" / "index.html"
LOG_DIR = PROJECT_ROOT / "logs"
STATE_DIR = PROJECT_ROOT / "state"
WORKSPACE_DIR = PROJECT_ROOT / "workspace"

MIME_TYPES: dict[str, str] = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".png": "image/png",
    ".ico": "image/x-icon",
}


def read_json_lines(path: Path) -> list[dict[str, Any]]:
    """Read a JSON-lines file and return a list of parsed entries."""
    if not path.exists():
        return []
    entries: list[dict[str, Any]] = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return entries


def get_log_dates() -> list[str]:
    """Return sorted list of dates for which log files exist."""
    dates: set[str] = set()
    for category in ("thoughts", "actions"):
        cat_dir = LOG_DIR / category
        if cat_dir.exists():
            for f in sorted(cat_dir.glob("*.log")):
                dates.add(f.stem)
    return sorted(dates, reverse=True)


def list_directory(path: Path, rel_root: Path) -> list[dict[str, Any]]:
    """List files in a directory, returning name, type, size."""
    entries: list[dict[str, Any]] = []
    try:
        for entry in sorted(path.iterdir(), key=lambda e: (not e.is_dir(), e.name)):
            entries.append({
                "name": entry.name,
                "type": "directory" if entry.is_dir() else "file",
                "size": entry.stat().st_size if entry.is_file() else 0,
            })
    except PermissionError:
        pass
    return entries


class LogViewerHandler(http.server.BaseHTTPRequestHandler):
    """HTTP request handler for the log viewer."""

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress default logging."""
        pass

    def _send_json(self, data: Any, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, indent=2, default=str).encode())

    def _send_text(self, text: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(text.encode())

    def _send_file(self, path: Path) -> None:
        ext = path.suffix.lower()
        mime = MIME_TYPES.get(ext, "application/octet-stream")
        try:
            content = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(content)
        except FileNotFoundError:
            self.send_response(404)
            self.end_headers()

    def _not_found(self, msg: str = "Not found") -> None:
        self._send_json({"error": msg}, 404)

    def _error(self, msg: str, status: int = 500) -> None:
        self._send_json({"error": msg}, status)

    def do_GET(self) -> None:
        path = self.path.split("?")[0]
        query = self._parse_query()

        try:
            if path == "/" or path == "/index.html":
                self._send_file(INDEX_PATH)
            elif path == "/api/logs/dates":
                self._send_json(get_log_dates())
            elif path == "/api/logs/thoughts":
                self._handle_logs("thoughts", query)
            elif path == "/api/logs/actions":
                self._handle_logs("actions", query)
            elif path == "/api/logs/updates":
                self._handle_logs("updates", query)
            elif path == "/api/state":
                self._handle_state()
            elif path == "/api/workspace/list":
                self._handle_workspace_list(query)
            elif path == "/api/workspace/file":
                self._handle_workspace_file(query)
            else:
                self._send_file(PROJECT_ROOT / "logs-viewer" / path.lstrip("/"))
        except Exception as e:
            self._error(str(e))

    def _parse_query(self) -> dict[str, str]:
        query: dict[str, str] = {}
        if "?" in self.path:
            for part in self.path.split("?", 1)[1].split("&"):
                if "=" in part:
                    k, v = part.split("=", 1)
                    query[k] = v
        return query

    def _handle_logs(self, category: str, query: dict[str, str]) -> None:
        date = query.get("date", "")
        if not date:
            dates = get_log_dates()
            if dates:
                date = dates[0]
            else:
                self._send_json([])
                return
        log_path = LOG_DIR / category / f"{date}.log"
        entries = read_json_lines(log_path)
        self._send_json(entries)

    def _handle_state(self) -> None:
        state_file = STATE_DIR / "state.json"
        if state_file.exists():
            data = json.loads(state_file.read_text())
            # Strip recent_logs to keep the response small
            data.pop("recent_logs", None)
            self._send_json(data)
        else:
            self._send_json({"error": "No state file"})

    def _handle_workspace_list(self, query: dict[str, str]) -> None:
        subpath = query.get("path", "")
        target = WORKSPACE_DIR
        if subpath:
            # Prevent path traversal
            sub = Path(subpath).relative_to("/")
            target = (WORKSPACE_DIR / sub).resolve()
            if not str(target).startswith(str(WORKSPACE_DIR.resolve())):
                self._send_json({"error": "Invalid path"}, 403)
                return
        if target.is_dir():
            entries = list_directory(target, WORKSPACE_DIR)
            rel = str(target.relative_to(WORKSPACE_DIR)) if target != WORKSPACE_DIR else ""
            self._send_json({"path": f"/{rel}", "entries": entries})
        else:
            self._send_json({"error": "Not a directory"}, 404)

    def _handle_workspace_file(self, query: dict[str, str]) -> None:
        path_str = query.get("path", "")
        if not path_str:
            self._send_json({"error": "Missing path"}, 400)
            return
        # Prevent path traversal
        sub = Path(path_str).relative_to("/")
        target = (WORKSPACE_DIR / sub).resolve()
        if not str(target).startswith(str(WORKSPACE_DIR.resolve())):
            self._send_json({"error": "Invalid path"}, 403)
            return
        if target.is_file():
            try:
                content = target.read_text()
                self._send_json({"path": path_str, "content": content})
            except UnicodeDecodeError:
                self._send_json({"path": path_str, "error": "Binary file"}, 400)
        else:
            self._send_json({"error": "File not found"}, 404)


def get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def main() -> None:
    port = int(os.getenv("HAL9000_VIEWER_PORT", "8080"))
    server = http.server.HTTPServer(("0.0.0.0", port), LogViewerHandler)
    print(f"HAL9000 log viewer: http://localhost:{port}", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.", file=sys.stderr)
        server.server_close()


if __name__ == "__main__":
    main()
