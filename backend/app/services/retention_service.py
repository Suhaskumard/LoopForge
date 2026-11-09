"""Data lifecycle for an organization (Phase 10, ADR-0017): retention, export, deletion.

- `run_retention`: deletes FINISHED tasks (completed/failed/escalated/cancelled) older than the
  organization's `retention_days`. Running tasks are never touched. Age is the task's creation time.
- `export_org`: a zip of JSON describing the organization's data. It never contains password hashes,
  tokens, API keys or source-file contents beyond what the final report already carries.
- `delete_org_data`: removes every project/task (rows and workspace files) but keeps the
  organization, its members and its audit log (the audit log is append-only by design).

Not covered (documented limits): LangGraph checkpoint files and backups outside the app.
"""

import io
import json
import logging
import shutil
import uuid
import zipfile
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.database.models import (
    ApprovalRequest,
    CodeComment,
    Job,
    Membership,
    Organization,
    Pipeline,
    PipelineStep,
    Project,
    PublishRequest,
    RegressionWatch,
    RepairHistory,
    RunLease,
    Task,
    User,
)
from app.services import report_service, workspace

log = logging.getLogger("loopforge.retention")

FINISHED = ("COMPLETED", "FAILED", "ESCALATED", "CANCELLED")


def _remove_workspace(task_id: uuid.UUID) -> None:
    root = workspace.workspace_root()
    target = (root / str(task_id)).resolve()
    if target.parent == root and target.is_dir():  # never follow a path out of the workspace root
        shutil.rmtree(target, ignore_errors=True)


# Tables with a foreign key to tasks.id that the ORM does NOT cascade (iterations, audit events and
# requirements are cascaded by the `Task` relationships). SQLite does not enforce foreign keys by
# default, PostgreSQL does: a table missing here makes deleting a task fail with a
# ForeignKeyViolation on PostgreSQL only. A test fails if a new table referencing tasks is added
# without being listed.
TASK_DEPENDENTS = (
    RepairHistory,
    ApprovalRequest,
    RunLease,
    Job,
    PublishRequest,
    CodeComment,  # Round 9
    RegressionWatch,  # Round 9
)


def purge_task(db: Session, task: Task) -> None:
    """Delete one task with everything that hangs off it, then its files."""
    task_id = task.id
    for model in TASK_DEPENDENTS:
        db.execute(delete(model).where(model.task_id == task_id))
    db.delete(task)  # iterations, agent runs, test results, artifacts, events, requirements cascade
    db.commit()
    _remove_workspace(task_id)


def _org_tasks(db: Session, org_id: uuid.UUID) -> list[Task]:
    return list(
        db.scalars(
            select(Task)
            .join(Project, Task.project_id == Project.id)
            .where(Project.org_id == org_id)
            .order_by(Task.created_at, Task.id)
        )
    )


def run_retention(db: Session, org: Organization, now: datetime | None = None) -> int:
    if org.retention_days is None:
        return 0
    current = now or datetime.now(timezone.utc).replace(tzinfo=None)
    cutoff = current - timedelta(days=org.retention_days)
    old = [t for t in _org_tasks(db, org.id) if t.status in FINISHED and t.created_at < cutoff]
    for task in old:
        purge_task(db, task)
    return len(old)


def purge_project_pipelines(db: Session, project_id: uuid.UUID) -> None:
    """Round 12: pipelines reference their project; remove them (and their steps) first."""
    ids = list(db.scalars(select(Pipeline.id).where(Pipeline.project_id == project_id)))
    if ids:
        db.execute(delete(PipelineStep).where(PipelineStep.pipeline_id.in_(ids)))
        db.execute(delete(Pipeline).where(Pipeline.id.in_(ids)))


def delete_org_data(db: Session, org: Organization) -> int:
    tasks = _org_tasks(db, org.id)
    for task in tasks:
        purge_task(db, task)
    for project in db.scalars(select(Project).where(Project.org_id == org.id)):
        purge_project_pipelines(db, project.id)
        db.delete(project)
    db.commit()
    return len(tasks)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def export_org(db: Session, org: Organization) -> bytes:
    """Zip: organization, members, projects and tasks as JSON, plus reports/<task>.json."""
    members = db.execute(
        select(User.email, Membership.role)
        .join(Membership, Membership.user_id == User.id)
        .where(Membership.org_id == org.id)
        .order_by(User.email)
    ).all()
    projects = list(db.scalars(select(Project).where(Project.org_id == org.id)))
    tasks = _org_tasks(db, org.id)
    files: dict[str, Any] = {
        "organization.json": {
            "id": str(org.id),
            "name": org.name,
            "slug": org.slug,
            "token_quota_month": org.token_quota_month,
            "max_tasks_month": org.max_tasks_month,
            "retention_days": org.retention_days,
            "redact_pii": org.redact_pii,
            "created_at": _iso(org.created_at),
        },
        "members.json": [{"email": e, "role": r} for e, r in members],
        "projects.json": [
            {
                "id": str(p.id),
                "name": p.name,
                "language": p.language,
                "created_at": _iso(p.created_at),
            }
            for p in projects
        ],
        "tasks.json": [
            {
                "id": str(t.id),
                "project_id": str(t.project_id),
                "requirement": t.requirement,
                "status": t.status,
                "iterations": t.current_iteration,
                "created_at": _iso(t.created_at),
            }
            for t in tasks
        ],
    }
    for task in tasks:
        try:
            files[f"reports/{task.id}.json"] = json.loads(
                report_service.build_report(db, task).model_dump_json()
            )
        except Exception:  # a task without a report yet (e.g. pending) simply has none
            log.warning("export: no report for task %s", task.id)
            continue
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, payload in files.items():
            z.writestr(name, json.dumps(payload, indent=2, default=str))
    return buf.getvalue()


__all__ = ["delete_org_data", "export_org", "purge_task", "run_retention"]
