from dataclasses import dataclass


@dataclass(frozen=True)
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(
            self.prompt_tokens + other.prompt_tokens,
            self.completion_tokens + other.completion_tokens,
        )


class TokenBudgetExceeded(Exception):
    pass


class TokenTracker:
    """Accumulates token usage for one task; the budget is enforced by the backend (spec §13.3)."""

    def __init__(self, budget: int, used: int = 0) -> None:
        self.budget = budget
        self.used = used

    def add(self, usage: Usage) -> None:
        self.used += usage.total

    @property
    def exceeded(self) -> bool:
        return self.used >= self.budget

    def check(self) -> None:
        if self.exceeded:
            raise TokenBudgetExceeded(f"token budget exhausted ({self.used}/{self.budget})")
