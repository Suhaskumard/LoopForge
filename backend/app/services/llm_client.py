"""LLM access behind a small interface (ADR-0007).

`OpenAIClient` is the real implementation; `FakeLLMClient` replays canned outputs so the whole
platform can be tested deterministically without a key or network.
"""

import json
import logging
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Generic, Protocol, TypeVar

import openai
from pydantic import BaseModel, ValidationError

from app.config import settings
from app.utils.token_tracker import Usage

log = logging.getLogger("loopforge.llm")

T = TypeVar("T", bound=BaseModel)


class LLMError(Exception):
    """Non-recoverable LLM failure (auth, bad request, retries exhausted)."""


class LLMTimeout(LLMError):
    pass


class LLMOutputError(LLMError):
    """The model answered, but not with valid, schema-conforming JSON."""


@dataclass(frozen=True)
class LLMResult(Generic[T]):
    parsed: T
    usage: Usage


class LLMClient(Protocol):
    def complete_json(self, *, system: str, user: str, response_model: type[T]) -> LLMResult[T]: ...


def parse_output(raw: str | None, response_model: type[T]) -> T:
    """Validate raw model text against the schema; raise LLMOutputError (never coerce)."""
    if not raw or not raw.strip():
        raise LLMOutputError("empty model output")
    try:
        return response_model.model_validate_json(raw)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:8]
        )
        raise LLMOutputError(f"output failed schema validation: {problems}") from None


# ---------------------------------------------------------------------------------------------
# Real client
# ---------------------------------------------------------------------------------------------

_TRANSIENT = (openai.RateLimitError, openai.APIConnectionError, openai.InternalServerError)


class OpenAIClient:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        client: Any | None = None,
        sleep: Callable[[float], None] = time.sleep,
        max_retries: int | None = None,
    ) -> None:
        self.model = model or settings.openai_model
        if not self.model:
            raise LLMError("OPENAI_MODEL is not configured")
        if client is None:
            key = api_key or settings.openai_api_key
            if not key:
                raise LLMError("OPENAI_API_KEY is not configured")
            client = openai.OpenAI(api_key=key, timeout=settings.llm_timeout_seconds, max_retries=0)
        self._client = client
        self._sleep = sleep
        self.max_retries = settings.llm_max_retries if max_retries is None else max_retries

    def _backoff(self, attempt: int) -> float:
        return float(
            min(settings.llm_backoff_base_seconds * (2**attempt), settings.llm_backoff_max_seconds)
        )

    def complete_json(self, *, system: str, user: str, response_model: type[T]) -> LLMResult[T]:
        schema = response_model.model_json_schema()
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": response_model.__name__, "schema": schema},
            },
        }
        last: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self._client.chat.completions.create(**kwargs)
            except openai.APITimeoutError as exc:  # subclass of APIConnectionError: check first
                last = exc
            except _TRANSIENT as exc:
                last = exc
            except openai.APIStatusError as exc:
                if exc.status_code >= 500:
                    last = exc
                else:  # 4xx: retrying cannot help
                    raise LLMError(f"OpenAI request rejected ({exc.status_code})") from exc
            except openai.OpenAIError as exc:
                raise LLMError(f"OpenAI error: {type(exc).__name__}") from exc
            else:
                usage_obj = getattr(response, "usage", None)
                usage = Usage(
                    int(getattr(usage_obj, "prompt_tokens", 0) or 0),
                    int(getattr(usage_obj, "completion_tokens", 0) or 0),
                )
                content = response.choices[0].message.content if response.choices else None
                return LLMResult(parse_output(content, response_model), usage)
            if attempt < self.max_retries:
                delay = self._backoff(attempt)
                log.warning(
                    "transient LLM error %s; retry %d in %.1fs",
                    type(last).__name__,
                    attempt + 1,
                    delay,
                )
                self._sleep(delay)
        if isinstance(last, openai.APITimeoutError):
            raise LLMTimeout("OpenAI request timed out after retries") from last
        raise LLMError(f"OpenAI unavailable after retries: {type(last).__name__}") from last


# ---------------------------------------------------------------------------------------------
# Deterministic fake
# ---------------------------------------------------------------------------------------------


@dataclass
class FakeCall:
    system: str
    user: str
    response_model: str


@dataclass
class FakeLLMClient:
    """Replays queued outputs in order. Items: BaseModel | dict | str (raw text) | Exception."""

    responses: deque[Any] = field(default_factory=deque)
    calls: list[FakeCall] = field(default_factory=list)

    def queue(self, *items: Any) -> "FakeLLMClient":
        self.responses.extend(items)
        return self

    def complete_json(self, *, system: str, user: str, response_model: type[T]) -> LLMResult[T]:
        self.calls.append(FakeCall(system, user, response_model.__name__))
        if not self.responses:
            raise LLMError("FakeLLMClient: no canned response queued")
        item = self.responses.popleft()
        if isinstance(item, Exception):
            raise item
        if isinstance(item, BaseModel):
            raw = item.model_dump_json()
        elif isinstance(item, dict):
            raw = json.dumps(item)
        else:
            raw = str(item)
        # deterministic, non-zero token estimate (~4 chars/token)
        usage = Usage(max(1, (len(system) + len(user)) // 4), max(1, len(raw) // 4))
        return LLMResult(parse_output(raw, response_model), usage)


def get_llm_client() -> LLMClient:
    """Factory/dependency. `fake` serves the built-in demo (never allowed in production)."""
    if settings.llm_provider == "fake":
        from app.demo.employee_management import demo_responses

        return FakeLLMClient().queue(*demo_responses())
    return OpenAIClient()
