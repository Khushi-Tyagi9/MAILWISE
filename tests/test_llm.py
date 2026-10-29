import httpx
import groq
import pytest

from app import llm


def status_error(cls, status, headers=None):
    request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    response = httpx.Response(status, headers=headers or {}, request=request)
    return cls("error", response=response, body=None)


def connection_error():
    return groq.APIConnectionError(request=httpx.Request("POST", "https://api.groq.com"))


def test_chat_returns_content_and_uses_configured_model(fake_groq):
    fake_groq.reply("hello")
    assert llm.chat("hi") == "hello"
    assert fake_groq.calls[0]["model"] == llm.config.groq_model


def test_retries_429_then_succeeds(fake_groq):
    fake_groq.reply(status_error(groq.RateLimitError, 429), "ok")
    assert llm.chat("hi") == "ok"
    assert len(fake_groq.calls) == 2


def test_retries_5xx_and_connection_errors(fake_groq):
    fake_groq.reply(
        status_error(groq.InternalServerError, 503),
        connection_error(),
        "ok",
    )
    assert llm.chat("hi") == "ok"
    assert len(fake_groq.calls) == 3


def test_retry_after_header_is_respected(fake_groq, monkeypatch):
    sleeps = []
    monkeypatch.setattr(llm, "_sleep", sleeps.append)
    fake_groq.reply(status_error(groq.RateLimitError, 429, {"retry-after": "7"}), "ok")
    llm.chat("hi")
    assert sleeps and sleeps[0] >= 7


def test_gives_up_after_bounded_attempts(fake_groq):
    fake_groq.reply(*[status_error(groq.RateLimitError, 429) for _ in range(llm.MAX_ATTEMPTS + 3)])
    with pytest.raises(llm.LLMError, match="after"):
        llm.chat("hi")
    assert len(fake_groq.calls) == llm.MAX_ATTEMPTS


def test_404_is_not_retried_and_points_to_list_models(fake_groq, capsys):
    fake_groq.reply(status_error(groq.NotFoundError, 404), "never reached")
    with pytest.raises(llm.LLMError, match="list_models.py"):
        llm.chat("hi")
    assert len(fake_groq.calls) == 1
    assert "list_models.py" in capsys.readouterr().out


def test_other_4xx_is_not_retried(fake_groq):
    fake_groq.reply(status_error(groq.AuthenticationError, 401), "never reached")
    with pytest.raises(llm.LLMError):
        llm.chat("hi")
    assert len(fake_groq.calls) == 1


def test_backoff_grows_and_is_capped():
    exc = status_error(groq.RateLimitError, 429)
    first = max(llm._backoff(0, exc) for _ in range(50))
    later = min(llm._backoff(3, exc) for _ in range(50))
    assert first <= llm.BASE_DELAY
    assert later >= llm.BASE_DELAY
    assert max(llm._backoff(20, exc) for _ in range(50)) <= llm.MAX_DELAY
