"""Isolated per-task workspaces. The Builder can only ever write inside `<root>/<task>/iter_<n>/`.

Defence in depth: paths are validated by the schema, re-resolved here, symlinks/junctions are
refused, every write is atomic, and all paths are validated *before* any file is written so a
rejected output leaves nothing behind.
"""

import hashlib
import os
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import settings
from app.database.models import Artifact
from app.schemas.plan import FileChange, validate_relative_path


class WorkspaceError(Exception):
    pass


@dataclass(frozen=True)
class WrittenFile:
    path: str
    sha256: str
    size: int
    artifact_id: uuid.UUID


def workspace_root() -> Path:
    return Path(settings.workspace_root).resolve()


def iteration_dir(task_id: uuid.UUID, iteration_number: int) -> Path:
    return workspace_root() / str(task_id) / f"iter_{iteration_number}"


def _is_link(p: Path) -> bool:
    return p.is_symlink() or p.is_junction()


def resolve_safe(base: Path, rel: str) -> Path:
    """Return the absolute target for `rel` under `base`, or raise WorkspaceError."""
    try:
        validate_relative_path(rel)
    except ValueError as exc:
        raise WorkspaceError(f"unsafe path {rel!r}: {exc}") from None
    base_resolved = base.resolve()
    current = base_resolved
    for part in rel.split("/"):
        current = current / part
        if _is_link(current):
            raise WorkspaceError(f"symbolic links are not allowed: {rel!r}")
    resolved = current.resolve()
    if not resolved.is_relative_to(base_resolved):
        raise WorkspaceError(f"path escapes the workspace: {rel!r}")
    return resolved


def _atomic_write(target: Path, content: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=".tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
        os.replace(tmp, target)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def write_changes(
    db: Session,
    *,
    task_id: uuid.UUID,
    iteration_id: uuid.UUID,
    iteration_number: int,
    changes: list[FileChange],
) -> list[WrittenFile]:
    base = iteration_dir(task_id, iteration_number)
    base.mkdir(parents=True, exist_ok=True)
    # Phase A: validate every path first so a bad one aborts before anything is written.
    targets = [(c, resolve_safe(base, c.path)) for c in changes]
    # Phase B: write.
    written: list[WrittenFile] = []
    for change, target in targets:
        _atomic_write(target, change.content)
        digest = hashlib.sha256(change.content.encode("utf-8")).hexdigest()
        artifact = Artifact(
            iteration_id=iteration_id,
            artifact_type="source",
            file_name=change.path,
            storage_path=str(target),
            file_hash=digest,
        )
        db.add(artifact)
        db.flush()
        written.append(
            WrittenFile(change.path, digest, len(change.content.encode("utf-8")), artifact.id)
        )
    db.commit()
    return written


def read_file(base: Path, rel: str, max_bytes: int = 500_000) -> str:
    target = resolve_safe(base, rel)
    if not target.is_file():
        raise WorkspaceError(f"no such file: {rel!r}")
    if target.stat().st_size > max_bytes:
        raise WorkspaceError("file too large to display")
    return target.read_text(encoding="utf-8")


def log_dir(task_id: uuid.UUID, iteration_number: int) -> Path:
    return workspace_root() / str(task_id) / "logs" / f"iter_{iteration_number}"


def out_dir(task_id: uuid.UUID, iteration_number: int) -> Path:
    """Writable scratch directory mounted into the sandbox (reports); never holds source."""
    return workspace_root() / str(task_id) / "out" / f"iter_{iteration_number}"


def write_log(
    db: Session,
    *,
    task_id: uuid.UUID,
    iteration_id: uuid.UUID,
    iteration_number: int,
    name: str,
    content: str,
) -> Artifact:
    """Store execution output as a `log` artifact (spec 3.6)."""
    base = log_dir(task_id, iteration_number)
    base.mkdir(parents=True, exist_ok=True)
    target = resolve_safe(base, name)
    _atomic_write(target, content)
    artifact = Artifact(
        iteration_id=iteration_id,
        artifact_type="log",
        file_name=name,
        storage_path=str(target),
        file_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
    )
    db.add(artifact)
    db.commit()
    return artifact


def list_source_files(base: Path) -> list[str]:
    """Relative POSIX paths of every regular file under `base` (symlinks/temp files skipped)."""
    out: list[str] = []
    for p in sorted(base.rglob("*")):
        if p.is_file() and not _is_link(p) and not p.name.startswith(".tmp-"):
            out.append(p.relative_to(base).as_posix())
    return out


def fork_iteration(
    db: Session,
    *,
    task_id: uuid.UUID,
    from_number: int,
    to_iteration_id: uuid.UUID,
    to_number: int,
    changes: list[FileChange],
) -> list[WrittenFile]:
    """Create iteration N+1 as a copy of N with `changes` applied (idempotent, spec §5.5).

    Every file of the new version is registered as a `source` artifact with its sha256, so each
    iteration is a complete, independently inspectable snapshot.
    """
    src = iteration_dir(task_id, from_number)
    dest = iteration_dir(task_id, to_number)
    dest.mkdir(parents=True, exist_ok=True)
    # Validate everything before touching the destination.
    existing = list_source_files(src)
    for rel in existing:
        resolve_safe(src, rel)
    targets = [(c, resolve_safe(dest, c.path)) for c in changes]
    for rel in existing:
        _atomic_write(resolve_safe(dest, rel), (src / rel).read_text(encoding="utf-8"))
    for change, target in targets:
        _atomic_write(target, change.content)

    for old in db.query(Artifact).filter_by(iteration_id=to_iteration_id, artifact_type="source"):
        db.delete(old)
    db.flush()
    written: list[WrittenFile] = []
    for rel in list_source_files(dest):
        text = (dest / rel).read_text(encoding="utf-8")
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        artifact = Artifact(
            iteration_id=to_iteration_id,
            artifact_type="source",
            file_name=rel,
            storage_path=str(dest / rel),
            file_hash=digest,
        )
        db.add(artifact)
        db.flush()
        written.append(WrittenFile(rel, digest, len(text.encode("utf-8")), artifact.id))
    db.commit()
    return written


def diff_iterations(
    task_id: uuid.UUID, old_number: int | None, new_number: int
) -> list[dict[str, str]]:
    """Unified diffs of every file that differs between two iterations."""
    import difflib

    new_base = iteration_dir(task_id, new_number)
    old_base = iteration_dir(task_id, old_number) if old_number is not None else None
    old_files = set(list_source_files(old_base)) if old_base and old_base.is_dir() else set()
    new_files = set(list_source_files(new_base)) if new_base.is_dir() else set()
    out: list[dict[str, str]] = []
    for rel in sorted(old_files | new_files):
        before = (
            (old_base / rel).read_text(encoding="utf-8") if old_base and rel in old_files else ""
        )
        after = (new_base / rel).read_text(encoding="utf-8") if rel in new_files else ""
        if before == after and rel in old_files and rel in new_files:
            continue
        status = (
            "added" if rel not in old_files else "removed" if rel not in new_files else "modified"
        )
        diff = "".join(
            difflib.unified_diff(
                before.splitlines(keepends=True),
                after.splitlines(keepends=True),
                fromfile=f"iter_{old_number}/{rel}" if old_number is not None else "/dev/null",
                tofile=f"iter_{new_number}/{rel}",
            )
        )
        out.append({"path": rel, "status": status, "diff": diff})
    return out
