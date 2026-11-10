"""LLM provider clients."""
from __future__ import annotations

from ..config import get_settings
from .base import LLMClient, LLMResponse
from .pricing import price_for

__all__ = ["LLMClient", "LLMResponse", "get_client"]


def get_client() -> LLMClient:
    settings = get_settings()
    price_for(settings.llm_model if settings.llm_provider != "fake" else "fake")  # no silent Rs 0 costs
    if settings.llm_provider == "anthropic":
        from .anthropic_client import AnthropicClient

        return AnthropicClient(settings.anthropic_api_key, settings.llm_model)
    if settings.llm_provider == "openai_compat":
        from .openai_compat import OpenAICompatClient

        return OpenAICompatClient(settings.openai_base_url, settings.openai_api_key, settings.llm_model)
    if settings.llm_provider == "fake":
        from .fake import FakeClient

        return FakeClient()
    raise ValueError(f"Unknown LLM_PROVIDER {settings.llm_provider!r}")