"""Strict schemas for agent outputs. Anything that does not validate is rejected (never coerced)."""

import re
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

RequirementType = Literal["functional", "non_functional", "security", "performance"]
Priority = Literal["critical", "high", "medium", "low"]

ALLOWED_EXTENSIONS = {".py", ".txt", ".md", ".toml", ".ini", ".cfg", ".json", ".yml", ".yaml"}
MAX_PATH_LENGTH = 200
MAX_FILE_CHARS = 200_000
MAX_TOTAL_CHARS = 1_000_000
MAX_FILES = 40

_DRIVE = re.compile(r"^[A-Za-z]:")
_REQ_ID = re.compile(r"^REQ-\d{3}$")
_PROJECT_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_DEPENDENCY = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_.\-]*(\[[A-Za-z0-9_,\-]+\])?(==[0-9][0-9A-Za-z.\-]*)?$"
)


def validate_relative_path(value: str) -> str:
    """Workspace-relative POSIX path: no traversal, absolute/drive/UNC, hidden or odd extensions."""
    if not value or len(value) > MAX_PATH_LENGTH:
        raise ValueError("path must be 1..200 characters")
    if "\x00" in value or "\\" in value:
        raise ValueError("path contains forbidden characters")
    if value.startswith("/") or _DRIVE.match(value):
        raise ValueError("path must be relative")
    parts = value.split("/")
    for part in parts:
        if part in ("", ".", ".."):
            raise ValueError("path contains empty or traversal segments")
        if part.startswith("."):
            raise ValueError("hidden files and directories are not allowed")
    suffix = "." + parts[-1].rsplit(".", 1)[-1].lower() if "." in parts[-1] else ""
    if suffix not in ALLOWED_EXTENSIONS:
        raise ValueError(f"file extension not allowed: {suffix or '(none)'}")
    return value


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class RequirementItem(_Strict):
    req_id: str
    description: str = Field(min_length=3, max_length=1000)
    type: RequirementType = "functional"
    priority: Priority = "medium"

    @field_validator("req_id")
    @classmethod
    def _id_format(cls, v: str) -> str:
        if not _REQ_ID.match(v):
            raise ValueError("req_id must look like REQ-001")
        return v


class PlannedFile(_Strict):
    path: str
    purpose: str = Field(min_length=3, max_length=500)
    implements: list[str] = Field(default_factory=list)

    @field_validator("path")
    @classmethod
    def _path(cls, v: str) -> str:
        return validate_relative_path(v)


class ProjectPlan(_Strict):
    project_name: str
    framework: Literal["FastAPI"] = "FastAPI"
    requirements: list[RequirementItem] = Field(min_length=1, max_length=50)
    acceptance_criteria: list[str] = Field(min_length=1, max_length=30)
    files: list[PlannedFile] = Field(min_length=1, max_length=MAX_FILES)
    dependencies: list[str] = Field(default_factory=list, max_length=40)

    @field_validator("project_name")
    @classmethod
    def _name(cls, v: str) -> str:
        if not _PROJECT_NAME.match(v):
            raise ValueError("project_name must be snake_case, 1..64 chars")
        return v

    @field_validator("acceptance_criteria")
    @classmethod
    def _criteria(cls, v: list[str]) -> list[str]:
        if any(not c.strip() or len(c) > 500 for c in v):
            raise ValueError("acceptance criteria must be non-empty and <=500 chars")
        return v

    @field_validator("dependencies")
    @classmethod
    def _deps(cls, v: list[str]) -> list[str]:
        for dep in v:
            if not _DEPENDENCY.match(dep):
                raise ValueError(f"invalid dependency specifier: {dep!r}")
        return v

    @model_validator(mode="after")
    def _consistency(self) -> Self:
        ids = [r.req_id for r in self.requirements]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate requirement ids")
        paths = [f.path for f in self.files]
        if len(set(paths)) != len(paths):
            raise ValueError("duplicate file paths in plan")
        if "requirements.txt" not in paths:
            raise ValueError("plan must include requirements.txt")
        unknown = {i for f in self.files for i in f.implements} - set(ids)
        if unknown:
            raise ValueError(f"files reference unknown requirement ids: {sorted(unknown)}")
        return self


class FileChange(_Strict):
    # File contents must be preserved byte-for-byte (indentation, trailing newline).
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    path: str
    content: str = Field(max_length=MAX_FILE_CHARS)
    action: Literal["create", "modify"] = "create"

    @field_validator("path")
    @classmethod
    def _path(cls, v: str) -> str:
        return validate_relative_path(v)


class BuilderOutput(_Strict):
    files: list[FileChange] = Field(min_length=1, max_length=MAX_FILES)

    @model_validator(mode="after")
    def _consistency(self) -> Self:
        paths = [f.path for f in self.files]
        if len(set(paths)) != len(paths):
            raise ValueError("duplicate file paths in builder output")
        if "requirements.txt" not in paths:
            raise ValueError("builder output must include requirements.txt")
        if sum(len(f.content) for f in self.files) > MAX_TOTAL_CHARS:
            raise ValueError("builder output too large")
        return self
