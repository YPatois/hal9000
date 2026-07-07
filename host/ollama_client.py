"""Ollama API client for the host daemon.
Provides generate() for single-turn and chat() for conversation-based calls.
Probes /api/show at init to determine model context_length at runtime."""
from __future__ import annotations

import json
import time
from typing import Any

import httpx


DEFAULT_BUDGET_RATIO = 0.75
FALLBACK_CONTEXT_LENGTH = 32768


class OllamaClient:
    def __init__(self, base_url: str, model: str, timeout: int = 300) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.context_length: int = self._probe_context_length()

    def _probe_context_length(self) -> int:
        try:
            with httpx.Client(timeout=10) as client:
                resp = client.post(
                    f"{self.base_url}/api/show",
                    json={"model": self.model},
                    headers={"Content-Type": "application/json"},
                )
                resp.raise_for_status()
                data = resp.json()
            info = data.get("model_info", {}) or {}
            raw = 0
            for k, v in info.items():
                if k.endswith(".context_length") and isinstance(v, (int, float)) and v:
                    raw = int(v)
                    break
            if raw:
                return int(raw)
            return FALLBACK_CONTEXT_LENGTH
        except Exception:
            return FALLBACK_CONTEXT_LENGTH

    def max_input_chars(self, budget_ratio: float | None = None) -> int:
        ratio = budget_ratio if budget_ratio is not None else DEFAULT_BUDGET_RATIO
        budget_tokens = int(self.context_length * ratio)
        return int(budget_tokens * 3.5)

    def chat(
        self,
        messages: list[dict[str, str]],
    ) -> tuple[str, float, int, int]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
        }
        start = time.time()
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(
                f"{self.base_url}/api/chat",
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()
        duration = time.time() - start
        content = data.get("message", {}).get("content", "")
        prompt_eval = data.get("prompt_eval_count", 0) or 0
        eval_count = data.get("eval_count", 0) or 0
        return content, duration, prompt_eval, eval_count

    def generate(self, prompt: str) -> tuple[str, float]:
        payload: dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
        }
        start = time.time()
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(
                f"{self.base_url}/api/generate",
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()
        duration = time.time() - start
        return data.get("response", ""), duration
