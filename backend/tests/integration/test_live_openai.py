"""Optional smoke test against the real OpenAI API. Skipped unless OPENAI_API_KEY and
OPENAI_MODEL are set in the environment; run with: pytest -m live"""

import os

import pytest
from pydantic import BaseModel

from app.services.llm_client import OpenAIClient

pytestmark = pytest.mark.live


class Echo(BaseModel):
    word: str


@pytest.mark.skipif(
    not (os.environ.get("OPENAI_API_KEY") and os.environ.get("OPENAI_MODEL")),
    reason="OPENAI_API_KEY / OPENAI_MODEL not set",
)
def test_real_model_returns_schema_valid_json():
    result = OpenAIClient().complete_json(
        system="Reply with JSON only.", user='Return {"word": "ok"}.', response_model=Echo
    )
    assert result.parsed.word and result.usage.total > 0
