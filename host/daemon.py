"""Host daemon — Unix socket server for the HAL9000 agent.
Single point of control: all Ollama calls, logging, and operator messages
flow through this daemon before reaching the container agent."""
from __future__ import annotations

import atexit
import json
import os
import re
import signal
import socket
import sys
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from host.config import HostConfig
from host.logger import FileLogger
from host.ollama_client import OllamaClient

PID_FILE = "host.pid"


def parse_tags(text: str) -> tuple[str, str]:
    """Extract <thinking> and <reflection> content from response text.
    Returns (thinking, reflection)."""
    thinking = ""
    match = re.search(r"<thinking>(.*?)</thinking>", text, re.DOTALL)
    if match:
        thinking = match.group(1).strip()
    reflection = ""
    match = re.search(r"<reflection>(.*?)</reflection>", text, re.DOTALL)
    if match:
        reflection = match.group(1).strip()
    return thinking, reflection


class HostDaemon:
    def __init__(self, config: HostConfig) -> None:
        self.config = config
        self.logger = FileLogger(config.log_dir)
        self.ollama = OllamaClient(config.ollama_url, config.model, config.agent_timeout)
        self.running = True
        self._ring: deque[dict[str, Any]] = deque(maxlen=config.max_history)
        self._agent_state: dict[str, Any] = {"turn": 0, "last_summary": ""}
        self._load_state()

    def _load_state(self) -> None:
        state_file = self.config.state_dir / "state.json"
        if state_file.exists():
            try:
                saved = json.loads(state_file.read_text())
                self._agent_state = saved.get("agent", {})
                self._ring.extend(saved.get("recent_logs", []))
            except (json.JSONDecodeError, OSError):
                pass

    def _save_state(self) -> None:
        self.config.state_dir.mkdir(parents=True, exist_ok=True)
        state = {
            "turn": self._agent_state.get("turn", 0),
            "start_time": self.config.start_time,
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "agent": self._agent_state,
            "recent_logs": list(self._ring),
        }
        (self.config.state_dir / "state.json").write_text(json.dumps(state, indent=2, default=str))

    def handle_message(self, msg: dict[str, Any]) -> dict[str, Any]:
        msg_type = msg.get("type", "")
        try:
            if msg_type == "ping":
                return {"pong": True}
            elif msg_type == "get_context":
                return self._handle_get_context()
            elif msg_type == "think":
                return self._handle_think(msg.get("context", ""))
            elif msg_type == "log":
                return self._handle_log(msg)
            else:
                return {"error": f"Unknown message type: {msg_type}"}
        except Exception as e:
            return {"error": str(e)}

    def _handle_get_context(self) -> dict[str, Any]:
        operator_msgs = self._read_operator_messages()
        logs = list(self._ring)
        return {
            "preprompt": self.config.preprompt,
            "logs": logs,
            "operator_messages": operator_msgs,
            "agent_state": self._agent_state,
        }

    def _handle_think(self, context: str) -> dict[str, Any]:
        response, duration = self.ollama.generate(context)
        turn = self._agent_state.get("turn", 0) + 1
        self._agent_state["turn"] = turn

        thinking, reflection = parse_tags(response)

        entry: dict[str, Any] = {
            "type": "thought",
            "turn": turn,
            "text": response,
            "thinking": thinking if thinking else None,
            "reflection": reflection if reflection else None,
            "duration_ms": int(duration * 1000),
            "model": self.config.model,
        }
        self.logger.write("thoughts", entry)
        self._ring.append(entry)
        self._save_state()
        return {"response": response, "duration_ms": int(duration * 1000)}

    def _handle_log(self, msg: dict[str, Any]) -> dict[str, Any]:
        data = msg.get("data", {})
        category = msg.get("category", "updates")
        data["model"] = self.config.model
        data["turn"] = self._agent_state.get("turn", 0)
        self.logger.write(category, data)
        self._ring.append(data)

        if msg.get("action_type") == "state_update":
            self._agent_state.update(data.get("state", {}))
            self._save_state()
        return {"ok": True}

    def _read_operator_messages(self) -> list[dict[str, Any]]:
        inbox = self.config.state_dir / "inbox"
        if not inbox.exists():
            return []
        messages: list[dict[str, Any]] = []
        for f in sorted(inbox.glob("*.json")):
            try:
                messages.append(json.loads(f.read_text()))
                f.unlink()
            except (json.JSONDecodeError, OSError):
                pass
        return messages

    def _ensure_socket_dir(self) -> None:
        sock_dir = os.path.dirname(self.config.socket_path)
        os.makedirs(sock_dir, exist_ok=True)
        try:
            os.unlink(self.config.socket_path)
        except OSError:
            pass

    def run(self) -> None:
        self._ensure_socket_dir()
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        atexit.register(self._cleanup_with_server, server)
        server.bind(self.config.socket_path)
        server.listen(5)
        os.chmod(self.config.socket_path, 0o777)

        print(f"[host] Daemon listening on {self.config.socket_path}", file=sys.stderr)
        print(f"[host] Model: {self.config.model}", file=sys.stderr)

        while self.running:
            try:
                conn, _ = server.accept()
            except OSError:
                break
            with conn:
                buffer = b""
                while self.running:
                    try:
                        data = conn.recv(65536)
                        if not data:
                            break
                        buffer += data
                        while b"\n" in buffer:
                            line, buffer = buffer.split(b"\n", 1)
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                msg = json.loads(line)
                                response = self.handle_message(msg)
                                conn.sendall((json.dumps(response) + "\n").encode())
                            except json.JSONDecodeError:
                                conn.sendall(
                                    (json.dumps({"error": "invalid JSON"}) + "\n").encode()
                                )
                    except OSError:
                        break

        server.close()
        self._cleanup()

    def _cleanup(self) -> None:
        self._save_state()
        try:
            os.unlink(self.config.socket_path)
        except OSError:
            pass

    def _cleanup_with_server(self, server: socket.socket) -> None:
        try:
            server.close()
        except (OSError, AttributeError):
            pass
        try:
            self._save_state()
        except Exception:
            pass
        try:
            os.unlink(self.config.socket_path)
        except OSError:
            pass

    def shutdown(self) -> None:
        self.running = False


def main() -> None:
    config = HostConfig()
    config.start_time = datetime.now(timezone.utc).isoformat()
    daemon = HostDaemon(config)

    def signal_handler(signum: int, frame: Any) -> None:
        print("\n[host] Shutting down...", file=sys.stderr)
        daemon.shutdown()

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    daemon.run()


if __name__ == "__main__":
    main()
