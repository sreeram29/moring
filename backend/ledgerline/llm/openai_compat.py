"""Client for any OpenAI-compatible /chat/completions endpoint.

Works with OpenAI, Gemini's OpenAI-compatible endpoint, Groq, OpenRouter, vLLM and local
Ollama (OPENAI_BASE_URL=http://localhost:11434/v1, no key needed).
"""
from __future__ import annotations

import os
import time

import httpx

from .base import LLMResponse


RETRY_STATUS = {408, 409, 425, 429, 500, 502, 503, 504, 529}  # transient; 401/402/403/404 are not retried
MAX_RETRIES = 3


def _wait_seconds(attempt: int, response: httpx.Response | None) -> float:
    """Honour Retry-After when the provider sends it, otherwise back off 1s, 2s, 4s."""
    if response is not None:
        try:
            return min(float(response.headers.get("retry-after", "")), 30.0)
        except ValueError:
            pass
    return float(min(2 ** attempt, 20))


_last_call = 0.0


def _pace() -> None:
    """Optional: LLM_MIN_INTERVAL_SECONDS keeps calls at least that far apart (for per-minute limits)."""
    global _last_call
    interval = float(os.getenv("LLM_MIN_INTERVAL_SECONDS") or 0)
    if interval > 0:
        wait = _last_call + interval - time.monotonic()
        if wait > 0:
            time.sleep(wait)
    _last_call = time.monotonic()


class OpenAICompatClient:
    def __init__(self, base_url: str, api_key: str | None, model: str, timeout: float = 120.0):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def _post_with_retries(self, headers: dict, payload: dict) -> httpx.Response:
        for attempt in range(MAX_RETRIES + 1):
            _pace()
            try:
                response = httpx.post(f"{self.base_url}/chat/completions", headers=headers,
                                      timeout=self.timeout, json=payload)
            except (httpx.TimeoutException, httpx.TransportError):
                if attempt == MAX_RETRIES:
                    raise
                time.sleep(_wait_seconds(attempt, None))
                continue
            if response.status_code in RETRY_STATUS and attempt < MAX_RETRIES:
                time.sleep(_wait_seconds(attempt, response))
                continue
            return response
        raise RuntimeError("unreachable")

    def complete(self, system: str, prompt: str, max_tokens: int = 2000) -> LLMResponse:
        started = time.monotonic()
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        # Reasoning models spend output tokens on thinking; 2000 was often used up before any answer appeared.
        limit = int(os.getenv("LLM_MAX_TOKENS") or 0) or max(max_tokens, 8000)
        payload = {
            "model": self.model,
            "max_tokens": limit,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        }
        reasoning = (os.getenv("LLM_REASONING") or "").strip().lower()  # off | low | medium | high
        if reasoning == "off":
            payload["reasoning"] = {"enabled": False}
        elif reasoning:
            payload["reasoning"] = {"effort": reasoning}
        response = self._post_with_retries(headers, payload)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:  # keep the provider's own explanation (daily cap, no credit, ...)
            raise httpx.HTTPStatusError(f"{exc} | provider said: {response.text[:300]}",
                                        request=exc.request, response=exc.response) from exc
        body = response.json()
        usage = body.get("usage") or {}
        choice = body["choices"][0]
        text = choice["message"].get("content") or ""
        if not text.strip() and choice.get("finish_reason") == "length":
            raise ValueError("the model used all its output tokens before answering "
                             "(raise LLM_MAX_TOKENS or set LLM_REASONING=off)")
        return LLMResponse(
            text=text,
            model=self.model,
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            latency_ms=int((time.monotonic() - started) * 1000),
        )
