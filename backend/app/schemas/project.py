import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.execution.languages import get_profile


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    language: str = "python"

    @field_validator("language")
    @classmethod
    def _supported(cls, v: str) -> str:
        return get_profile(v).name  # ValueError -> 422; typescript/ts/js normalise to javascript


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    description: str
    language: str
    version: int
    created_at: datetime
