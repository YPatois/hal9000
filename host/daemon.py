"""Host daemon — Unix socket server for the HAL9000 agent.
Conversation-based: maintains a running chat history for Ollama's /api/chat.
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
import threading
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from host.config import HostConfig
from host.logger import FileLogger
from host.ollama_client import OllamaClient

PID_FILE = "host.pid"
SYSTEM = "system"
USER = "user"
ASSISTANT = "assistant"


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
        self._conversation: list[dict[str, str]] = []
        self._pending_results: list[dict[str, Any]] = []
        self._last_activity: float = time.time()
        self._last_archived_turn: int = 0

        self._load_state()

    # ── Conversation logging ──────────────────────────────────────────

    def _log_conversation_turn(
        self,
        turn: int,
        user_content: str,
        assistant_content: str,
    ) -> None:
        """Log a complete turn (user + assistant) to the conversation log."""
        conv_dir = self.config.log_dir / "conversations"
        conv_dir.mkdir(parents=True, exist_ok=True)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        log_path = conv_dir / f"{today}.jsonl"
        entry = {
            "type": "conversation_turn",
            "turn": turn,
            "ts": datetime.now(timezone.utc).isoformat(),
            "user": user_content,
            "assistant": assistant_content,
            "model": self.config.model,
        }
        with open(log_path, "a") as f:
            f.write(json.dumps(entry, default=str) + "\n")

    def _archive_conversation(self) -> None:
        """Save full conversation as a complete archive log, then clear.

        Only archives if new turns exist since last archive.
        """
        msg_count = len(self._conversation)
        current_turn = self._agent_state.get("turn", 0)
        if msg_count <= 1 or current_turn <= self._last_archived_turn:
            return

        archive_dir = self.config.log_dir / "conversations"
        archive_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")
        archive_path = archive_dir / f"archive_{ts}.json"

        archive = {
            "type": "conversation_archive",
            "turn": current_turn,
            "start_time": self.config.start_time,
            "archived_at": datetime.now(timezone.utc).isoformat(),
            "model": self.config.model,
            "message_count": msg_count,
            "last_archived_turn": self._last_archived_turn,
            "conversation": list(self._conversation),
        }
        archive_path.write_text(json.dumps(archive, indent=2, default=str))
        self._last_archived_turn = current_turn

        self.logger.write("updates", {
            "type": "conversation_archive",
            "turn": current_turn,
            "archived_to": archive_path.name,
            "message_count": msg_count,
        })

    def _restore_from_archives(self) -> list[dict[str, str]]:
        """Reconstruct conversation from archive + turn logs.

        Used when state.json conversation is missing/corrupted.
        Returns the reconstructed conversation list.
        """
        conv_dir = self.config.log_dir / "conversations"
        if not conv_dir.is_dir():
            return []

        # Collect all turn entries from jsonl logs, sorted by turn
        turns: list[dict[str, Any]] = []
        for f in sorted(conv_dir.glob("*.jsonl")):
            try:
                for line in f.read_text().splitlines():
                    if not line.strip():
                        continue
                    entry = json.loads(line)
                    if entry.get("type") == "conversation_turn":
                        turns.append(entry)
            except (json.JSONDecodeError, OSError):
                pass

        # Also load full archives
        archives: list[dict[str, Any]] = []
        for f in sorted(conv_dir.glob("archive_*.json")):
            try:
                archives.append(json.loads(f.read_text()))
            except (json.JSONDecodeError, OSError):
                pass

        # Merge: start with most recent archive's conversation, then append turns
        reconstructed: list[dict[str, str]] = []
        if archives:
            reconstructed = list(archives[-1]["conversation"])

        # Deduplicate turns already in archive
        existing_turns: set[int] = set()
        for m in reconstructed:
            if m.get("role") == USER:
                existing_turns.add(
                    archives[-1].get("turn", 0) - len(reconstructed)
                )

        # Filter to entries newer than the archive
        archive_turn = archives[-1].get("turn", 0) if archives else 0
        for t in turns:
            if t["turn"] > archive_turn:
                reconstructed.append({"role": USER, "content": t["user"]})
                reconstructed.append({"role": ASSISTANT, "content": t["assistant"]})

        return reconstructed

    # ── State persistence ─────────────────────────────────────────────

    def _load_state(self) -> None:
        state_file = self.config.state_dir / "state.json"
        if state_file.exists():
            try:
                saved = json.loads(state_file.read_text())
                self._agent_state = saved.get("agent", {})
                self._ring.extend(saved.get("recent_logs", []))
                self._last_archived_turn = saved.get("last_archived_turn", 0)
                conv = saved.get("conversation", [])
                if conv:
                    self._conversation = conv
                else:
                    self._init_conversation()
                    self._restore_from_logs()
            except (json.JSONDecodeError, OSError):
                self._init_conversation()
                self._restore_from_logs()
        else:
            self._init_conversation()

    def _restore_from_logs(self) -> None:
        """Fill conversation with archived turns up to 3/4 of context budget.

        Called when state.json has no conversation. Reads daily conversation
        logs from logs/conversations/*.jsonl and fills the working conversation
        with recent turns, oldest-first, up to ~75% of the context budget.
        """
        conv_dir = self.config.log_dir / "conversations"
        if not conv_dir.is_dir():
            return

        # Collect all turn entries from daily jsonl logs, newest first
        all_turns: list[dict] = []
        for f in sorted(conv_dir.glob("*.jsonl"), reverse=True):
            try:
                for line in f.read_text().splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    entry = json.loads(line)
                    if entry.get("user") and entry.get("assistant") and entry.get("turn"):
                        all_turns.append(entry)
            except (json.JSONDecodeError, OSError):
                pass

        if not all_turns:
            return

        all_turns.sort(key=lambda e: e["turn"])  # oldest first

        budget = self.ollama.max_input_chars(self.config.context_budget_ratio)
        fill_budget = int(budget * 0.75)
        sys_len = len(self._conversation[0]["content"]) if self._conversation else 0
        available = fill_budget - sys_len
        if available <= 0:
            return

        selected: list[dict] = []
        added = 0
        # Start from the newest turns, pick what fits, collect in a list
        for entry in reversed(all_turns):
            user_len = len(entry.get("user", ""))
            asst_len = len(entry.get("assistant", ""))
            pair_size = user_len + asst_len + 64
            if pair_size > available and added > 0:
                break
            if pair_size > available:
                continue
            available -= pair_size
            selected.append(entry)
            added += 1

        # Insert selected turns in chronological order (oldest first)
        for i, entry in enumerate(reversed(selected)):
            idx = 1 + i * 2
            self._conversation.insert(idx, {"role": USER, "content": entry["user"]})
            self._conversation.insert(idx + 1, {"role": ASSISTANT, "content": entry["assistant"]})

        if added:
            print(
                f"[host] Restored {added} turns from archives ({fill_budget - available:,}/{fill_budget:,} chars)",
                file=sys.stderr,
            )

    # ── Conversation management ──────────────────────────────────────

    def _init_conversation(self) -> None:
        self._conversation.clear()
        system_content = self.config.preprompt
        docs = self._read_description_docs()
        if docs:
            system_content += "\n\n---\n" + docs
        self._conversation.append({"role": SYSTEM, "content": system_content})

    def _read_description_docs(self) -> str:
        desc_dir = self.config.log_dir / "description"
        if not desc_dir.is_dir():
            return ""
        parts: list[str] = []
        for f in sorted(desc_dir.glob("*.md"), key=lambda p: p.name):
            try:
                parts.append(f.read_text().strip())
            except OSError:
                pass
        return "\n\n".join(parts)

    def _add_user_message(self, content: str) -> None:
        self._conversation.append({"role": USER, "content": content})

    def _add_assistant_message(self, content: str) -> None:
        self._conversation.append({"role": ASSISTANT, "content": content})

    def _conversation_chars(self) -> int:
        return sum(len(m["content"]) for m in self._conversation)

    def _trim_conversation(self) -> None:
        budget = self.ollama.max_input_chars(self.config.context_budget_ratio)
        has_system = (
            len(self._conversation) > 0
            and self._conversation[0]["role"] == SYSTEM
        )
        while self._conversation_chars() > budget and len(self._conversation) > 2:
            self._archive_conversation()
            idx = 1 if has_system else 0
            self._conversation.pop(idx)

    def _nudge_if_idle(self) -> None:
        timeout = self.config.idle_timeout
        if timeout <= 0:
            return
        elapsed = time.time() - self._last_activity
        if elapsed > timeout:
            nudge_text = (
                f"[Idle Nudge] No activity for {int(elapsed)} seconds. "
                "You are an autonomous agent — continue whatever work "
                "you were doing."
            )
            self._add_user_message(nudge_text)
            self.logger.write("thoughts", {
                "type": "idle_nudge",
                "elapsed_seconds": int(elapsed),
                "text": nudge_text,
                "model": self.config.model,
            })

    def _save_state(self) -> None:
        self.config.state_dir.mkdir(parents=True, exist_ok=True)
        state = {
            "turn": self._agent_state.get("turn", 0),
            "start_time": self.config.start_time,
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "agent": self._agent_state,
            "recent_logs": list(self._ring),
            "conversation": self._conversation,
            "last_archived_turn": self._last_archived_turn,
        }
        (self.config.state_dir / "state.json").write_text(
            json.dumps(state, indent=2, default=str)
        )

    # ── Message handlers ─────────────────────────────────────────────

    def _build_system_context(self, turn: int) -> dict[str, Any]:
        return {
            "model": self.config.model,
            "context_length": self.ollama.context_length,
            "turn": turn,
            "conversation_turns": len(self._conversation) // 2,
            "last_action": self._agent_state.get("last_action_result", "none"),
            "container": "8GB RAM, 2 CPUs",
            "shell_timeout": "~120 seconds per `run` command",
            "turn_interval": "~30 seconds between turns",
        }

    def _build_turn_content(self, operator_msgs: list[dict[str, Any]]) -> str:
        turn = self._agent_state.get("turn", 0) + 1
        parts: list[str] = []

        sys_ctx = self._build_system_context(turn)
        parts.append("[System Context]")
        for key, value in sys_ctx.items():
            label = key.replace("_", " ").title()
            parts.append(f"  {label}: {value}")

        if self._pending_results:
            parts.append("")
            parts.append("[Action Results]")
            for r in self._pending_results:
                action = r.get("action", "?")
                result = r.get("result", {})
                if result.get("success"):
                    parts.append(f"  Action '{action}' succeeded.")
                else:
                    parts.append(
                        f"  Action '{action}' failed: {result.get('error', 'unknown')}"
                    )
                stdout = result.get("stdout", "")
                if stdout:
                    lines = stdout.splitlines()
                    if len(lines) > 40:
                        lines = lines[:40] + ["... (truncated)"]
                    parts.append("  Output:")
                    for line in lines:
                        parts.append(f"    {line}")
                stderr = result.get("stderr", "")
                if stderr:
                    parts.append(f"  Stderr: {stderr[:2000]}")
            self._pending_results.clear()

        if operator_msgs:
            parts.append("")
            parts.append(
                ">>> OPERATOR MESSAGES - These require an immediate response <<<"
            )
            for msg in operator_msgs:
                ts = msg.get("timestamp", "?")
                parts.append(f"  [{ts}] Operator: {msg.get('text', '')}")
            parts.append(
                "You MUST respond to the operator message ABOVE before "
                "continuing your own tasks."
            )

        parts.append("")
        parts.append(
            f"Continue your work. Produce your next action or record your thoughts."
        )

        return "\n".join(parts)

    def _read_operator_messages(self) -> list[dict[str, Any]]:
        inbox = self.config.state_dir / "inbox"
        if not inbox.exists():
            return []
        messages: list[dict[str, Any]] = []
        for f in sorted(inbox.glob("*.json")):
            try:
                msg = json.loads(f.read_text())
                messages.append(msg)
                ts = datetime.now(timezone.utc).isoformat()
                entry: dict[str, Any] = {
                    "type": "operator_input",
                    "text": msg.get("text", ""),
                    "turn": self._agent_state.get("turn", 0),
                    "model": self.config.model,
                    "timestamp": ts,
                }
                self.logger.write("thoughts", entry)
                self.logger.write("updates", entry)
                f.unlink()
            except (json.JSONDecodeError, OSError):
                pass
        return messages

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
        self._nudge_if_idle()
        operator_msgs = self._read_operator_messages()
        turn = self._agent_state.get("turn", 0)
        logs = list(self._ring)
        return {
            "preprompt": self.config.preprompt,
            "logs": logs,
            "operator_messages": operator_msgs,
            "agent_state": self._agent_state,
            "system_context": {
                "model": self.config.model,
                "context_length": self.ollama.context_length,
                "turn": turn,
                "last_action": self._agent_state.get("last_action_result", "none"),
                "shell_timeout": "~120 seconds per `run` command",
                "turn_interval": "~30 seconds between turns",
                "container": "8GB RAM, 2 CPUs",
                "log_history_turns": "15 turns shown per context",
                "log_entry_max_chars": "4000 characters per entry (use run+cat for full content)",
                "full_content": "read files with `run` actions - `cat`, `head`, `tail`, `grep`",
            },
        }

    def _handle_think(self, context: str) -> dict[str, Any]:
        self._last_activity = time.time()
        turn = self._agent_state.get("turn", 0) + 1
        self._agent_state["turn"] = turn

        operator_msgs = self._read_operator_messages()
        user_content = self._build_turn_content(operator_msgs)
        self._add_user_message(user_content)

        response, duration, prompt_eval, eval_count = self.ollama.chat(
            self._conversation
        )

        self._add_assistant_message(response)
        self._log_conversation_turn(turn, user_content, response)
        self._trim_conversation()

        thinking, reflection = parse_tags(response)

        entry: dict[str, Any] = {
            "type": "thought",
            "turn": turn,
            "text": response,
            "thinking": thinking if thinking else None,
            "reflection": reflection if reflection else None,
            "duration_ms": int(duration * 1000),
            "model": self.config.model,
            "prompt_eval_count": prompt_eval,
            "eval_count": eval_count,
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

        if data.get("type") == "action_result":
            result = data.get("result", {})
            self._agent_state["last_action_result"] = (
                "success" if result.get("success") else "error"
            )
            self._pending_results.append(data)
        elif msg.get("action_type") == "state_update":
            self._agent_state.update(data.get("state", {}))
            self._save_state()
        return {"ok": True}

    # ── Socket server ────────────────────────────────────────────────

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
        print(
            f"[host] Context length: {self.ollama.context_length} tokens",
            file=sys.stderr,
        )

        while self.running:
            try:
                conn, _ = server.accept()
                t = threading.Thread(
                    target=self._serve_connection, args=(conn,), daemon=True
                )
                t.start()
            except OSError:
                break

        server.close()
        self._cleanup()

    def _serve_connection(self, conn: socket.socket) -> None:
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

    def _cleanup(self) -> None:
        self._archive_conversation()
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
            self._archive_conversation()
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
