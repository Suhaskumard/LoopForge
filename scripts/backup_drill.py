"""Backup and restore drill (SQLite, development): prove a backup can actually be restored.

Steps: build a real schema with the migrations, seed an organization with projects, tasks, workspace files
and an audit trail -> BACK UP (SQLite online-backup API + a tarball of the workspaces + a manifest with
checksums) -> verify the backup -> WIPE everything -> RESTORE -> verify that row counts, the audit log
contents and the workspace files are identical and that the append-only audit triggers survived. It also
proves a corrupted backup is refused instead of restored.

For PostgreSQL use scripts/backup.sh and scripts/restore.sh (same manifest idea; they could not be run in
the development environment). Exit status 0 = every check passed.

Usage: python scripts/backup_drill.py [--keep]
"""

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
TABLES = ("users", "organizations", "memberships", "projects", "tasks", "audit_log")


class BackupError(Exception):
    pass


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def tree_digest(root: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if p.is_file():
            h.update(str(p.relative_to(root)).replace("\\", "/").encode())
            h.update(sha256_file(p).encode())
    return h.hexdigest()


def fingerprint(db_file: Path, workspaces: Path) -> dict:
    con = sqlite3.connect(db_file)
    try:
        counts = {t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in TABLES}  # noqa: S608
        audit = con.execute(
            "SELECT id, action, target_id, created_at FROM audit_log ORDER BY created_at, id"
        ).fetchall()
    finally:
        con.close()
    return {
        "counts": counts,
        "audit_sha256": hashlib.sha256(json.dumps(audit, default=str).encode()).hexdigest(),
        "workspace_sha256": tree_digest(workspaces),
    }


def _fernet(key: bytes):
    from cryptography.fernet import Fernet  # already a runtime dependency (PyJWT needs it)

    return Fernet(key)


def new_key() -> bytes:
    from cryptography.fernet import Fernet

    return Fernet.generate_key()


def _encrypt_in_place(path: Path, key: bytes) -> Path:
    """Replace `path` with `path.enc` (Fernet: AES-128-CBC + HMAC). Whole file in memory: fine for a drill."""
    enc = path.with_name(path.name + ".enc")
    enc.write_bytes(_fernet(key).encrypt(path.read_bytes()))
    path.unlink()  # no plaintext copy is left in the backup directory
    return enc


def _decrypted(path: Path, key: bytes, scratch: Path) -> Path:
    from cryptography.fernet import InvalidToken

    try:
        data = _fernet(key).decrypt(path.read_bytes())
    except InvalidToken:
        raise BackupError(f"{path.name} cannot be decrypted: wrong key or tampered backup") from None
    out = scratch / path.name.removesuffix(".enc")
    out.write_bytes(data)
    return out


def backup(db_file: Path, workspaces: Path, out: Path, key: bytes | None = None) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    db_copy = out / "database.sqlite"
    src, dst = sqlite3.connect(db_file), sqlite3.connect(db_copy)
    try:
        src.backup(dst)  # consistent snapshot even while the app is writing
    finally:
        src.close()
        dst.close()
    archive = out / "workspaces.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(workspaces, arcname="workspaces")
    fp = fingerprint(db_copy, workspaces)  # computed from the plaintext copy, before encryption
    if key is not None:
        db_copy, archive = _encrypt_in_place(db_copy, key), _encrypt_in_place(archive, key)
    manifest = {
        "encrypted": key is not None,
        "database_sha256": sha256_file(db_copy),
        "workspaces_sha256": sha256_file(archive),
        "fingerprint": fp,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest


def verify_backup(backup_dir: Path) -> dict:
    manifest = json.loads((backup_dir / "manifest.json").read_text())
    suffix = ".enc" if manifest.get("encrypted") else ""
    for name, key in (
        (f"database.sqlite{suffix}", "database_sha256"),
        (f"workspaces.tar.gz{suffix}", "workspaces_sha256"),
    ):
        if sha256_file(backup_dir / name) != manifest[key]:
            raise BackupError(f"{name} does not match the manifest checksum: backup is corrupt")
    return manifest


def _safe_extract(archive: Path, dest: Path) -> None:
    with tarfile.open(archive) as tar:
        for member in tar.getmembers():
            target = (dest / member.name).resolve()
            if not str(target).startswith(str(dest.resolve())) or member.issym() or member.islnk():
                raise BackupError(f"unsafe path in archive: {member.name}")
        tar.extractall(dest, filter="data")  # noqa: S202 - members were validated above


def restore(backup_dir: Path, db_file: Path, workspaces: Path, key: bytes | None = None) -> None:
    manifest = verify_backup(backup_dir)  # never restore something that fails its own checksums
    db_src, archive = backup_dir / "database.sqlite", backup_dir / "workspaces.tar.gz"
    scratch = None
    if manifest.get("encrypted"):
        if key is None:
            raise BackupError("this backup is encrypted: a key is required to restore it")
        scratch = Path(tempfile.mkdtemp(prefix="loopforge_restore_"))
        try:
            db_src = _decrypted(backup_dir / "database.sqlite.enc", key, scratch)
            archive = _decrypted(backup_dir / "workspaces.tar.gz.enc", key, scratch)
        except BackupError:
            shutil.rmtree(scratch, ignore_errors=True)
            raise
    try:
        db_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(db_src, db_file)
        workspaces.parent.mkdir(parents=True, exist_ok=True)
        _safe_extract(archive, workspaces.parent)
    finally:
        if scratch is not None:
            shutil.rmtree(scratch, ignore_errors=True)


def seed(env: dict[str, str], workspaces: Path) -> None:
    code = f"""
import sys
sys.path.insert(0, {str(BACKEND)!r})
from app.database.models import User
from app.database.session import SessionLocal
from app.schemas.project import ProjectCreate
from app.services import audit_service, org_service, project_service, task_service
with SessionLocal() as db:
    user = User(email="backup@example.com", password_hash="x")
    db.add(user); db.commit()
    org = org_service.create_personal_org(db, user)
    project = project_service.create_project(db, org.id, user.id, ProjectCreate(name="p"))
    for i in range(3):
        t = task_service.create_task(db, project, f"Build service number {{i}} with tests please.", 5, [])
        audit_service.record(db, org_id=org.id, actor_id=user.id, action="task.create",
                             target_type="task", target_id=t.id, detail={{"n": i}})
        d = __import__("pathlib").Path({str(workspaces)!r}) / str(t.id) / "iter_1"
        d.mkdir(parents=True); (d / "app.py").write_text(f"x = {{i}}\\n")
"""
    subprocess.run([sys.executable, "-c", code], env=env, check=True, capture_output=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep", action="store_true")
    parser.add_argument(
        "--encrypt", action="store_true", help="encrypt the backup (Fernet) and prove the key matters"
    )
    args = parser.parse_args()
    key = new_key() if args.encrypt else None
    suffix = ".enc" if args.encrypt else ""
    work = Path(tempfile.mkdtemp(prefix="loopforge_backup_"))
    db_file, workspaces, bdir = (
        work / "live" / "app.db",
        work / "live" / "workspaces",
        work / "backup",
    )
    env = {k: v for k, v in os.environ.items() if not k.startswith(("DATABASE_URL", "TEST_"))}
    env.update(
        DATABASE_URL=f"sqlite:///{db_file}", WORKSPACE_ROOT=str(workspaces),
        ENVIRONMENT="development", PYTHONPATH=str(BACKEND),
    )  # fmt: skip
    db_file.parent.mkdir(parents=True)
    problems: list[str] = []
    try:
        subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND, env=env,
                       check=True, capture_output=True)  # fmt: skip
        seed(env, workspaces)
        before = fingerprint(db_file, workspaces)
        print(f"live data: {before['counts']}")

        manifest = backup(db_file, workspaces, bdir, key)
        verify_backup(bdir)
        print(
            f"backup written to {bdir.name}/ and verified ({manifest['database_sha256'][:12]}...)"
        )

        # a corrupted backup must be refused, not restored
        corrupt = work / "corrupt"
        shutil.copytree(bdir, corrupt)
        with (corrupt / f"database.sqlite{suffix}").open("r+b") as f:
            f.seek(100)
            f.write(b"\x00\xff\x00\xff")
        try:
            restore(corrupt, work / "x" / "app.db", work / "x" / "workspaces", key)
            problems.append("a corrupted backup was restored instead of refused")
        except BackupError as exc:
            print(f"corrupted backup refused: {exc}")

        if args.encrypt:
            blob = b"".join(p.read_bytes() for p in bdir.iterdir() if p.name != "manifest.json")
            if b"SQLite format 3" in blob or b"backup@example.com" in blob or b"x = 0" in blob:
                problems.append("plaintext is visible inside the encrypted backup")
            if any(p.name in ("database.sqlite", "workspaces.tar.gz") for p in bdir.iterdir()):
                problems.append("a plaintext copy was left next to the encrypted backup")
            for label, wrong in (("no key", None), ("a wrong key", new_key())):
                try:
                    restore(bdir, work / "y" / "app.db", work / "y" / "workspaces", wrong)
                    problems.append(f"an encrypted backup was restored with {label}")
                except BackupError as exc:
                    print(f"restore with {label} refused: {exc}")

        shutil.rmtree(work / "live")  # the disaster: database, checkpoints and workspaces are gone
        print("live data wiped")
        restore(bdir, db_file, workspaces, key)
        after = fingerprint(db_file, workspaces)
        print(f"restored data: {after['counts']}")
        for key in ("counts", "audit_sha256", "workspace_sha256"):
            if before[key] != after[key]:
                problems.append(f"{key} differs after restore")

        con = sqlite3.connect(db_file)
        try:
            if con.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                problems.append("SQLite integrity_check failed after restore")
            try:
                con.execute("UPDATE audit_log SET action = 'tampered'")
                problems.append("the restored audit_log accepted an UPDATE: triggers were lost")
            except sqlite3.DatabaseError:
                print("audit_log is still append-only after restore")
        finally:
            con.close()
    except Exception as exc:  # noqa: BLE001
        problems.append(f"{type(exc).__name__}: {exc}")
    finally:
        if args.keep:
            print(f"kept {work}")
        else:
            shutil.rmtree(work, ignore_errors=True)
    if problems:
        print("\nBACKUP DRILL: FAIL")
        for p in problems:
            print(f"  - {p}")
        return 1
    mode = "encrypted, wrong/missing key refused, " if args.encrypt else ""
    print(
        f"\nBACKUP DRILL: PASS ({mode}restored data and audit trail are identical; "
        "corruption is refused)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
