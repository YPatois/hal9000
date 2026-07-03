"""Daemon controller for HAL9000."""
from __future__ import annotations

import asyncio
import json
import os
import re
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import aiohttp
import httpx

from daemon.config import DaemonConfig
from daemon.context_builder import ContextBuilder
from daemon.log_record import LogRecord
from daemon.action_processor import ActionExtractor
from daemon.action_executor import ActionExecutor

OLLAMA_URL = os.getenv("HAL9000_OLLAMA_URL", "http://localhost:11434")


class LoopDaemon:
    """Main daemon that controls the agent loop."""

    def __init__(self, config: DaemonConfig) -> None:
        self.config = config
        self.running = True
        self.turn = 0
        self.log = LogRecord(config.log_dir)
        self.ctx = ContextBuilder(config.preprompt)
        self.actions = ActionExecutor(config.workspace_dir)
        self.extractor = ActionExtractor()
        
        self._agent_state: dict[str, Any] = {}
        state_file = config.state_dir / "state.json"
        if state_file.exists():
            self._agent_state = json.loads(state_file.read_text())
        
        self._session = aiohttp.ClientSession()

    def _save_state(self) -> None:
        state = {
            "turn": self.turn,
            "start_time": self.config.start_time,
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "agent": self._agent_state,
        }
        self.config.state_dir.mkdir(parents=True, exist_ok=True)
        (self.config.state_dir / "state.json").write_text(json.dumps(state, indent=2))

    def _log_action_result(self, action: dict, result: dict) -> None:
        self.log.write_entry("actions", {
            "type": "action_log",
            "turn": self.turn,
            "ts": datetime.now(timezone.utc).isoformat(),
            "action": action.get("type", "unknown"),
            "path": action.get("path", ""),
            "url": action.get("url", ""),
            "result": result,
        })

    def _build_context(self) -> str:
        recent = self.log.recent_entries(self.config.max_history, ["thoughts", "actions", "updates"])
        return self.ctx.build(self._agent_state, recent)

    async def call_agent(self, context: str) -> tuple[str, float]:
        """Call Ollama and get a response. THIS IS THE ONLY PLACE OLLAMA IS CALLED."""
        payload = json.dumps({
            "model": self.config.model,
            "prompt": context,
            "stream": False,
        })
        
        start = time.time()
        async with self._session.post(
            f"{OLLAMA_URL}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            timeout=aiohttp.ClientTimeout(total=self.config.agent_timeout),
        ) as resp:
            data = await resp.json()
        duration = time.time() - start
        
        return data.get("response", ""), duration

    def process_actions(self, response: str) -> list[dict]:
        """Extract and execute actions from agent response.
        
        Actions are logged before they are executed, ensuring the agent
        cannot hide or modify their trace.
        """
        text, actions = self.extractor.parse_response(response)
        
        for action in actions:
            meta = {
                "turn": self.turn + 1,
                "ts": datetime.now(timezone.utc).isoformat(),
                "model": self.config.model,
            }
            action["meta"] = meta
            self.log.write_entry("actions", {
                "type": "action_log",
                "turn": self.turn + 1,
                "ts": datetime.now(timezone.utc).isoformat(),
                "action": action.get("type", "unknown"),
                "path": action.get("path", ""),
                "url": action.get("url", ""),
                "pre_execution": True,
            })
            result = self.actions.execute_sync(action)
            self.log.write_entry("actions", {
                "type": "action_result",
                "turn": self.turn + 1,
                "ts": datetime.now(timezone.utc).isoformat(),
                "action": action.get("type", "unknown"),
                "path": action.get("path", ""),
                "url": action.get("url", ""),
                "result": result,
                "post_execution": True,
            })
        
        return actions

    async def run(self) -> None:
        """Main daemon loop."""
        print(f"[daemon] Starting autonomous loop", file=sys.stderr)
        print(f"[daemon] Model: {self.config.model}", file=sys.stderr)
        
        while self.running:
            context = self._build_context()
            prompt = f"SYSTEM TURN: {self.turn + 1}\n\n{context}"
            turn_start = time.time()
            
            print(f"[daemon] Turn {self.turn + 1}...", file=sys.stderr)
            
            try:
                response, duration = await self.call_agent(prompt)
                
                self.log.write_entry("thoughts", {
                    "type": "thought",
                    "turn": self.turn + 1,
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "text": response,
                    "duration_ms": int(duration * 1000),
                    "model": self.config.model,
                    "system_prompt": True,
                })
                
            except Exception as e:
                print(f"[daemon] Error in call: {e}", file=sys.stderr)
                response = f"[SYSTEM TURN {self.turn + 1}] Error: {e}"
                self.log.write_entry("thoughts", {
                    "type": "error",
                    "turn": self.turn + 1,
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "text": str(e),
                })
            
            self.process_actions(response)
            self.turn += 1
            self._save_state()
            
            delay = max(1, self.config.loop_interval - (time.time() - turn_start))
            if delay > 1:
                await asyncio.sleep(delay)

    async def shutdown(self) -> None:
        """Graceful shutdown."""
        print("\n[daemon] Shutting down...", file=sys.stderr)
        self.running = False
        self._save_state()
        await self._session.close()
        sys.exit(0)


def main() -> None:
    """Entry point for the HAL9000 daemon."""
    config = DaemonConfig()
    daemon = LoopDaemon(config)
    
    def signal_handler(signum: int, frame: Any) -> None:
        asyncio.run(daemon.shutdown())
    
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    
    asyncio.run(daemon.run())


if __name__ == "__main__":
    main()
