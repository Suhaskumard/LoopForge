"""Strict outputs for the Reviewer and Repair agents (Phase 4)."""

from typing import Self

from pydantic import ConfigDict, Field, model_validator

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


class TextEdit(_Strict):
    """One exact search/replace. Whitespace matters, so nothing is stripped."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)
    search: str = Field(min_length=1, max_length=20_000)
    replace: str = Field(max_length=20_000)


class PatchedFile(_Strict):
    """Edits to one existing file, valid only against the version whose sha256 is `base_sha256`."""

    path: str
    base_sha256: str = Field(min_length=64, max_length=64)
    edits: list[TextEdit] = Field(min_length=1, max_length=50)


class RepairPatchOutput(_Strict):
    """Phase 16 (`patch_edits`): whole files for new/rewritten files, edits for small changes."""

    root_cause: str = Field(min_length=3, max_length=2000)
    explanation: str = Field(min_length=3, max_length=2000)
    changes: list[FileChange] = Field(default_factory=list, max_length=MAX_FILES)
    patches: list[PatchedFile] = Field(default_factory=list, max_length=MAX_FILES)

    @model_validator(mode="after")
    def _consistency(self) -> Self:
        paths = [c.path for c in self.changes] + [p.path for p in self.patches]
        if not paths:
            raise ValueError("a repair must change at least one file")
        if len(set(paths)) != len(paths):
            raise ValueError("duplicate file paths in repair output")
        return self


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
