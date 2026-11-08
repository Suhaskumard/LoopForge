"""Attach an imported repository to a task as its seed (iteration 0)."""

from sqlalchemy.orm import Session

from app.database.models import AuditEvent, Task
from app.execution.languages import detect_language, get_profile
from app.services import repo_import, workspace
from app.services.repo_import import RepoImport, RepoImportError


def seed_task(db: Session, task: Task, result: RepoImport, ref: str) -> None:
    """Validate the import against the project language, write iter_0 and record the hash."""
    expected = get_profile(task.project.language).name
    found = detect_language(result.files)
    if found != expected:
        raise RepoImportError(
            f"the repository looks like {found} but the project language is {expected}"
        )
    workspace.write_seed(task.id, result.files)
    task.source_ref = ref[:300]
    task.source_hash = result.source_hash
    db.add(AuditEvent(task_id=task.id, event_type="repo_imported", event_data=result.summary()))
    db.commit()


def import_from_git(db: Session, task: Task) -> None:
    assert task.source_ref
    seed_task(db, task, repo_import.import_git(task.source_ref), task.source_ref)
