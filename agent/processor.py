"""Container-side agent loop — thin relay.
Connects to host daemon via Unix socket. All Ollama calls, logging, and
operator messages flow through the daemon. This process only executes
actions and reports results back to the host."""
from __future__ import annotations

import json
import os
import signal
import socket
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from daemon.action_processor import ActionExtractor
from daemon.action_executor import ActionExecutor

SOCKET_PATH = os.getenv("HAL9000_SOCKET_PATH", "/tmp/hal9000/daemon.sock")
LOOP_INTERVAL = int(os.getenv("HAL9000_LOOP_INTERVAL", "30"))
AGENT_TIMEOUT = int(os.getenv("HAL9000_AGENT_TIMEOUT", "600"))
WORKSPACE_DIR = Path(os.getenv("HAL9000_WORKSPACE_DIR", "/workspace"))
STATE_DIR = Path(os.getenv("HAL9000_STATE_DIR", "/state"))


class DaemonClient:
    """Client for communicating with the host daemon over a Unix socket."""

    def __init__(self, socket_path: str) -> None:
        self.socket_path = socket_path
        self._sock: socket.socket | None = None
        self._buffer = b""

    def connect(self) -> None:
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.connect(self.socket_path)

    def close(self) -> None:
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    def send(self, msg: dict[str, Any]) -> dict[str, Any]:
        if not self._sock:
            raise ConnectionError("Not connected")
        payload = json.dumps(msg) + "\n"
        self._sock.sendall(payload.encode())

        response_buf = b""
        while True:
            data = self._sock.recv(65536)
            if not data:
                raise ConnectionError("Connection closed")
            response_buf += data
            if b"\n" in response_buf:
                line, self._buffer = response_buf.split(b"\n", 1)
                return json.loads(line.decode())

    def get_context(self) -> dict[str, Any]:
        return self.send({"type": "get_context"})

    def think(self, context: str = "") -> str:
        result = self.send({"type": "think", "context": context})
        if "error" in result:
            raise RuntimeError(result["error"])
        return result["response"]

    def log(self, category: str, data: dict[str, Any]) -> None:
        self.send({"type": "log", "category": category, "data": data})


class AgentLoop:
    def __init__(self) -> None:
        self.client = DaemonClient(SOCKET_PATH)
        self.running = True
        self.turn = 0
        self.executor = ActionExecutor(WORKSPACE_DIR, STATE_DIR)
        self.extractor = ActionExtractor()

    def _log_action_result(
        self,
        action: dict[str, Any],
        result: dict[str, Any],
    ) -> None:
        entry: dict[str, Any] = {
            "type": "action_result",
            "turn": self.turn,
            "ts": datetime.now(timezone.utc).isoformat(),
            "action": action.get("type", "unknown"),
            "path": action.get("path", ""),
            "command": action.get("command", ""),
            "result": result,
        }
        self.client.log("actions", entry)

    def run(self) -> None:
        print(f"[agent] Connecting to daemon at {SOCKET_PATH}", file=sys.stderr)
        self.client.connect()
        print("[agent] Connected", file=sys.stderr)

        while self.running:
            self.turn += 1
            turn_start = time.time()

            try:
                print(f"[agent] Turn {self.turn}...", file=sys.stderr)

                try:
                    response = self.client.think()
                except RuntimeError as e:
                    print(f"[agent] Think error: {e}", file=sys.stderr)
                    delay = max(1, LOOP_INTERVAL - (time.time() - turn_start))
                    if delay > 1:
                        time.sleep(delay)
                    continue

                _, actions = self.extractor.parse_response(response)

                for action in actions:
                    action_meta = {
                        "turn": self.turn,
                        "ts": datetime.now(timezone.utc).isoformat(),
                    }
                    action["meta"] = action_meta

                    try:
                        result = self.executor.execute_sync(action)
                    except Exception as e:
                        result = {"error": str(e)}

                    self._log_action_result(action, result)

            except (ConnectionError, OSError) as e:
                print(f"[agent] Connection lost: {e}", file=sys.stderr)
                print("[agent] Reconnecting in 5s...", file=sys.stderr)
                self.client.close()
                time.sleep(5)
                try:
                    self.client.connect()
                    print("[agent] Reconnected", file=sys.stderr)
                except (ConnectionError, OSError):
                    print("[agent] Reconnect failed, retrying...", file=sys.stderr)
                continue

            except Exception as e:
                print(f"[agent] Unexpected error: {e}", file=sys.stderr)

            delay = max(1, LOOP_INTERVAL - (time.time() - turn_start))
            if delay > 1:
                time.sleep(delay)

        self.client.close()


def main() -> None:
    loop = AgentLoop()

    def signal_handler(signum: int, frame: Any) -> None:
        print("\n[agent] Shutting down...", file=sys.stderr)
        loop.running = False

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGCHLD, signal.SIG_IGN)

    loop.run()


if __name__ == "__main__":
    main()
