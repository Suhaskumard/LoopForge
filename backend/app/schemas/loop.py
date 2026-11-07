"""Strict outputs for the Reviewer and Repair agents (Phase 4)."""

from typing import Self

from pydantic import Field, model_validator

from app.schemas.plan import MAX_FILES, MAX_TOTAL_CHARS, FileChange, _Strict


class CriterionAssessment(_Strict):
    criterion: str = Field(min_length=1, max_length=500)
    met: bool
    evidence: str = Field(default="", max_length=1000)


class RequirementCoverage(_Strict):
    req_id: str
    covered: bool
    note: str = Field(default="", max_length=500)


class ReviewOutput(_Strict):
    critical_issues: list[str] = Field(default_factory=list, max_length=30)
    acceptance_criteria: list[CriterionAssessment] = Field(max_length=40)
    requirement_coverage: list[RequirementCoverage] = Field(default_factory=list, max_length=60)
    maintainability_notes: list[str] = Field(default_factory=list, max_length=20)
    quality_score: float = Field(ge=0.0, le=1.0)


class RepairOutput(_Strict):
    root_cause: str = Field(min_length=3, max_length=2000)
    explanation: str = Field(min_length=3, max_length=2000)
    changes: list[FileChange] = Field(min_length=1, max_length=MAX_FILES)

    @model_validator(mode="after")
    def _consistency(self) -> Self:
        paths = [c.path for c in self.changes]
        if len(set(paths)) != len(paths):
            raise ValueError("duplicate file paths in repair output")
        if sum(len(c.content) for c in self.changes) > MAX_TOTAL_CHARS:
            raise ValueError("repair output too large")
        return self
