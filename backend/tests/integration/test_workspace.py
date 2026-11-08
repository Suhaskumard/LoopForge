import hashlib
import os
import subprocess
import sys
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import Artifact, Iteration, Project, Task, User
from app.schemas.plan import FileChange
from app.services import org_service, workspace
from app.services.workspace import WorkspaceError, resolve_safe, write_changes


def _make_dir_link(link, target):
    """Directory symlink, or a Windows junction (no admin needed) as a fallback."""
    try:
        os.symlink(target, link, target_is_directory=True)
        return
    except (OSError, NotImplementedError):
        pass
    if sys.platform == "win32":
        r = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True
        )
        if r.returncode == 0:
            return
    pytest.skip("cannot create directory links on this system")


@pytest.fixture
def base(tmp_path):
    d = tmp_path / "base"
    d.mkdir()
    return d


@pytest.fixture
def db(tmp_path):
    from app.database.models import Base
    from app.database.session import make_engine

    engine = make_engine(f"sqlite:///{tmp_path / 'ws.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s
    engine.dispose()


@pytest.fixture
def iteration(db):
    user = User(email="w@x.com", password_hash="x")
    db.add(user)
    db.flush()
    org = org_service.create_personal_org(db, user)
    project = Project(user_id=user.id, org_id=org.id, name="p")
    db.add(project)
    db.flush()
    task = Task(project_id=project.id, requirement="r")
    db.add(task)
    db.flush()
    it = Iteration(task_id=task.id, iteration_number=1)
    db.add(it)
    db.commit()
    return it


def test_resolve_safe_accepts_nested_paths(base):
    target = resolve_safe(base, "app/sub/main.py")
    assert target == base.resolve() / "app" / "sub" / "main.py"


@pytest.mark.parametrize(
    "rel", ["../x.py", "a/../../x.py", "/etc/passwd.py", "C:/x.py", ".git/x.py", "x.exe", ""]
)
def test_resolve_safe_rejects_escapes(base, rel):
    with pytest.raises(WorkspaceError):
        resolve_safe(base, rel)


def test_resolve_safe_rejects_symlinked_directory(base, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    _make_dir_link(base / "link", outside)
    with pytest.raises(WorkspaceError, match="symbolic links"):
        resolve_safe(base, "link/evil.py")


def test_resolve_safe_rejects_symlinked_file(base, tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("top secret")
    try:
        os.symlink(secret, base / "leak.txt")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not permitted on this system")
    with pytest.raises(WorkspaceError, match="symbolic links"):
        resolve_safe(base, "leak.txt")


def test_write_changes_writes_hashes_and_records_artifacts(db, iteration):
    changes = [
        FileChange(path="app/main.py", content="print('hi')\n"),
        FileChange(path="requirements.txt", content="fastapi==0.115.6\n"),
    ]
    written = write_changes(
        db,
        task_id=iteration.task_id,
        iteration_id=iteration.id,
        iteration_number=1,
        changes=changes,
    )
    base = workspace.iteration_dir(iteration.task_id, 1)
    assert (base / "app" / "main.py").read_text() == "print('hi')\n"
    assert {w.path for w in written} == {"app/main.py", "requirements.txt"}
    expected = hashlib.sha256(b"print('hi')\n").hexdigest()
    assert next(w for w in written if w.path == "app/main.py").sha256 == expected
    rows = list(db.scalars(select(Artifact)))
    assert {r.file_name for r in rows} == {"app/main.py", "requirements.txt"}
    assert all(r.artifact_type == "source" for r in rows)
    # no temp files left behind
    assert not list(base.rglob(".tmp-*"))


def test_write_is_confined_and_validates_before_writing(db, iteration):
    """Even if a bad path slips past schema validation, nothing may be written."""
    good = FileChange(path="app/main.py", content="x")
    evil = FileChange.model_construct(path="../../evil.py", content="pwn", action="create")
    with pytest.raises(WorkspaceError):
        write_changes(
            db,
            task_id=iteration.task_id,
            iteration_id=iteration.id,
            iteration_number=1,
            changes=[good, evil],
        )
    base = workspace.iteration_dir(iteration.task_id, 1)
    assert not (base / "app" / "main.py").exists()  # the good file was NOT written either
    assert not (base.parent.parent / "evil.py").exists()
    assert list(db.scalars(select(Artifact))) == []


def test_modify_overwrites_atomically(db, iteration):
    kwargs = {"task_id": iteration.task_id, "iteration_id": iteration.id, "iteration_number": 1}
    write_changes(db, changes=[FileChange(path="a.py", content="v1")], **kwargs)
    write_changes(db, changes=[FileChange(path="a.py", content="v2", action="modify")], **kwargs)
    assert (workspace.iteration_dir(iteration.task_id, 1) / "a.py").read_text() == "v2"


def test_read_file_confined_and_limited(base):
    (base / "ok.py").write_text("hello")
    assert workspace.read_file(base, "ok.py") == "hello"
    with pytest.raises(WorkspaceError, match="no such file"):
        workspace.read_file(base, "missing.py")
    with pytest.raises(WorkspaceError):
        workspace.read_file(base, "../ok.py")
    (base / "big.py").write_text("x" * 100)
    with pytest.raises(WorkspaceError, match="too large"):
        workspace.read_file(base, "big.py", max_bytes=10)


def test_iteration_dirs_are_per_task_and_iteration():
    t1, t2 = uuid.uuid4(), uuid.uuid4()
    assert workspace.iteration_dir(t1, 1) != workspace.iteration_dir(t2, 1)
    assert workspace.iteration_dir(t1, 1) != workspace.iteration_dir(t1, 2)
    assert workspace.iteration_dir(t1, 1).is_relative_to(workspace.workspace_root())
