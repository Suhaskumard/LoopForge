"""Workspace knowledge graph and repair-memory views (Round 8)."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

NodeType = Literal["project", "task", "failure", "file"]
EdgeKind = Literal["contains", "failed_with", "touched", "learned_from", "chained_from", "rerun_of"]


class GraphNode(BaseModel):
    id: str
    type: NodeType
    label: str
    status: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


class GraphEdge(BaseModel):
    source: str
    target: str
    kind: EdgeKind


class GraphOut(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    truncated: bool = False


class RepairOut(BaseModel):
    id: uuid.UUID
    task_id: uuid.UUID
    task_requirement: str
    task_status: str
    learnable: bool
    failure_class: str
    failure_category: str
    fingerprint: str | None
    root_cause: str
    proposed_fix: str
    files_modified: list[Any]
    outcome: str
    regression_status: str
    tokens_used: int
    duration_seconds: float
    created_at: datetime
