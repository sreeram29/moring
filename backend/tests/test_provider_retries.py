"""A rate limit or a blip at the provider must not turn a good document into a processing_error."""
import json

import httpx
import pytest

from ledgerline.llm import openai_compat
from ledgerline.llm.openai_compat import OpenAICompatClient

URL = "https://example.test/v1/chat/completions"


def reply(status, headers=None, text="ok"):
    body = {"choices": [{"message": {"content": text}}], "usage": {"prompt_tokens": 10, "completion_tokens": 5}}
    return httpx.Response(status, json=body if status == 200 else {"error": "x"}, headers=headers or {},
                          request=httpx.Request("POST", URL))


@pytest.fixture
def sleeps(monkeypatch):
    waited = []
    monkeypatch.setattr(openai_compat.time, "sleep", lambda s: waited.append(s))
    return waited


def client():
    return OpenAICompatClient("https://example.test/v1", "key", "fake")


def script(monkeypatch, outcomes):
    calls = []

    def fake_post(*a, **k):
        calls.append(1)
        out = outcomes[len(calls) - 1]
        if isinstance(out, Exception):
            raise out
        return out

    monkeypatch.setattr(openai_compat.httpx, "post", fake_post)
    return calls


def test_rate_limit_is_retried_then_succeeds(monkeypatch, sleeps):
    calls = script(monkeypatch, [reply(429), reply(429), reply(200)])
    assert client().complete("s", "p").text == "ok"
    assert len(calls) == 3 and sleeps == [1.0, 2.0]


def test_retry_after_header_is_honoured(monkeypatch, sleeps):
    script(monkeypatch, [reply(429, {"retry-after": "7"}), reply(200)])
    client().complete("s", "p")
    assert sleeps == [7.0]


def test_timeouts_and_connection_errors_are_retried(monkeypatch, sleeps):
    calls = script(monkeypatch, [httpx.ReadTimeout("slow"), httpx.ConnectError("down"), reply(200)])
    assert client().complete("s", "p").text == "ok" and len(calls) == 3


def test_payment_required_is_not_retried(monkeypatch, sleeps):
    calls = script(monkeypatch, [reply(402), reply(200)])
    with pytest.raises(httpx.HTTPStatusError):
        client().complete("s", "p")
    assert len(calls) == 1 and sleeps == []


def test_gives_up_after_the_retry_limit(monkeypatch, sleeps):
    calls = script(monkeypatch, [reply(503)] * 4)
    with pytest.raises(httpx.HTTPStatusError):
        client().complete("s", "p")
    assert len(calls) == 4 and sleeps == [1.0, 2.0, 4.0]