from types import SimpleNamespace

import httpx
import openai
import pytest
from pydantic import BaseModel

from app.config import settings
from app.services.llm_client import (
    FakeLLMClient,
    LLMError,
    LLMOutputError,
    LLMTimeout,
    OpenAIClient,
    parse_output,
)
from app.utils.token_tracker import TokenBudgetExceeded, TokenTracker, Usage

REQ = httpx.Request("POST", "https://api.example/v1/chat/completions")


def _resp(code):
    return httpx.Response(code, request=REQ)


class Out(BaseModel):
    answer: int


def _completion(content, prompt=11, completion=7):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(prompt_tokens=prompt, completion_tokens=completion),
    )


class FakeSDK:
    """Stands in for openai.OpenAI: replays a script of results/exceptions."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = 0
        self.last_kwargs = None
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls += 1
        self.last_kwargs = kwargs
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _client(script, **kw):
    sleeps = []
    sdk = FakeSDK(script)
    c = OpenAIClient(model="test-model", client=sdk, sleep=sleeps.append, **kw)
    return c, sdk, sleeps


def _call(c):
    return c.complete_json(system="s", user="u", response_model=Out)


# ---- parse_output -------------------------------------------------------------------------


@pytest.mark.parametrize("raw", [None, "", "   ", "not json", '{"answer": "x"}', '{"nope": 1}'])
def test_parse_output_rejects_bad_text(raw):
    with pytest.raises(LLMOutputError):
        parse_output(raw, Out)


def test_parse_output_error_names_the_field():
    with pytest.raises(LLMOutputError, match="answer"):
        parse_output('{"answer": "x"}', Out)
    assert parse_output('{"answer": 3}', Out).answer == 3


# ---- OpenAIClient -------------------------------------------------------------------------


def test_success_parses_content_and_usage_and_sends_schema():
    c, sdk, sleeps = _client([_completion('{"answer": 42}')])
    result = _call(c)
    assert result.parsed.answer == 42
    assert (result.usage.prompt_tokens, result.usage.completion_tokens) == (11, 7)
    assert result.usage.total == 18 and sleeps == []
    kw = sdk.last_kwargs
    assert kw["model"] == "test-model"
    assert kw["response_format"]["type"] == "json_schema"
    assert kw["messages"][0] == {"role": "system", "content": "s"}


def test_transient_errors_retried_with_exponential_backoff():
    script = [
        openai.RateLimitError("rl", response=_resp(429), body=None),
        openai.APIConnectionError(request=REQ),
        openai.InternalServerError("boom", response=_resp(500), body=None),
        _completion('{"answer": 1}'),
    ]
    c, sdk, sleeps = _client(script, max_retries=3)
    assert _call(c).parsed.answer == 1
    assert sdk.calls == 4
    base = settings.llm_backoff_base_seconds
    assert sleeps == [base, base * 2, base * 4]


def test_retries_exhausted_raises_llm_error():
    script = [openai.RateLimitError("rl", response=_resp(429), body=None)] * 3
    c, sdk, sleeps = _client(script, max_retries=2)
    with pytest.raises(LLMError, match="unavailable"):
        _call(c)
    assert sdk.calls == 3 and len(sleeps) == 2  # no sleep after the final attempt


def test_timeout_after_retries_is_llm_timeout():
    script = [openai.APITimeoutError(request=REQ)] * 2
    c, sdk, _ = _client(script, max_retries=1)
    with pytest.raises(LLMTimeout):
        _call(c)
    assert sdk.calls == 2


@pytest.mark.parametrize("code", [400, 401, 403, 404, 422])
def test_client_errors_are_not_retried(code):
    err = openai.APIStatusError("bad", response=_resp(code), body=None)
    c, sdk, sleeps = _client([err, _completion('{"answer": 1}')], max_retries=3)
    with pytest.raises(LLMError, match=str(code)):
        _call(c)
    assert sdk.calls == 1 and sleeps == []


def test_5xx_status_error_is_retried():
    err = openai.APIStatusError("bad gateway", response=_resp(502), body=None)
    c, sdk, _ = _client([err, _completion('{"answer": 5}')], max_retries=1)
    assert _call(c).parsed.answer == 5 and sdk.calls == 2


def test_invalid_model_output_is_not_retried_by_client():
    c, sdk, _ = _client([_completion("garbage"), _completion('{"answer": 1}')], max_retries=3)
    with pytest.raises(LLMOutputError):
        _call(c)
    assert sdk.calls == 1  # agent layer owns the corrective retry


def test_empty_choices_and_missing_usage_handled():
    empty = SimpleNamespace(choices=[], usage=None)
    c, _, _ = _client([empty])
    with pytest.raises(LLMOutputError):
        _call(c)
    no_usage = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content='{"answer": 2}'))], usage=None
    )
    c2, _, _ = _client([no_usage])
    assert _call(c2).usage.total == 0


def test_backoff_is_capped():
    script = [openai.APIConnectionError(request=REQ)] * 9
    c, _, sleeps = _client(script, max_retries=8)
    with pytest.raises(LLMError):
        _call(c)
    assert max(sleeps) == settings.llm_backoff_max_seconds


def test_unknown_sdk_error_wrapped():
    c, _, _ = _client([openai.OpenAIError("weird")])
    with pytest.raises(LLMError, match="OpenAIError"):
        _call(c)


def test_configuration_errors(monkeypatch):
    monkeypatch.setattr(settings, "openai_model", "")
    with pytest.raises(LLMError, match="OPENAI_MODEL"):
        OpenAIClient(client=object())
    monkeypatch.setattr(settings, "openai_api_key", "")
    with pytest.raises(LLMError, match="OPENAI_API_KEY"):
        OpenAIClient(model="m")


def test_real_sdk_client_is_built_without_sdk_level_retries(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    c = OpenAIClient(model="m")
    assert c._client.max_retries == 0  # we own retry/backoff policy


# ---- FakeLLMClient ------------------------------------------------------------------------


def test_fake_client_replays_validates_and_records():
    f = FakeLLMClient().queue({"answer": 1}, Out(answer=2), '{"answer": 3}')
    assert [
        f.complete_json(system="a", user="b", response_model=Out).parsed.answer for _ in range(3)
    ] == [1, 2, 3]
    assert f.calls[0].user == "b" and f.calls[0].response_model == "Out"
    assert f.complete_json.__self__ is f


def test_fake_client_usage_is_nonzero_and_deterministic():
    one = (
        FakeLLMClient()
        .queue({"answer": 1})
        .complete_json(system="x" * 40, user="y" * 40, response_model=Out)
    )
    two = (
        FakeLLMClient()
        .queue({"answer": 1})
        .complete_json(system="x" * 40, user="y" * 40, response_model=Out)
    )
    assert one.usage == two.usage and one.usage.total > 0


def test_fake_client_errors():
    f = FakeLLMClient().queue({"wrong": 1}, RuntimeError("boom"))
    with pytest.raises(LLMOutputError):
        f.complete_json(system="", user="", response_model=Out)
    with pytest.raises(RuntimeError):
        f.complete_json(system="", user="", response_model=Out)
    with pytest.raises(LLMError, match="no canned response"):
        f.complete_json(system="", user="", response_model=Out)


# ---- token tracker ------------------------------------------------------------------------


def test_token_tracker_budget():
    t = TokenTracker(100)
    t.add(Usage(30, 20))
    assert t.used == 50 and not t.exceeded
    t.check()
    t.add(Usage(25, 25))
    assert t.exceeded
    with pytest.raises(TokenBudgetExceeded, match="100"):
        t.check()
    assert Usage(1, 2) + Usage(3, 4) == Usage(4, 6)
