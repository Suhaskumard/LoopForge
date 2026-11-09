"""Import an existing repository as the starting workspace of a task (Phase 8, ADR-0015).

The repository is UNTRUSTED input. Nothing here executes repository code; it is only read, filtered
and copied as text. Everything that survives the filters is then subject to the same workspace path
rules as generated code (`schemas.plan.validate_relative_path`), so a seeded tree can always be
forked into later iterations.

Defences: archive/file-count/size/depth limits, zip-slip and absolute paths, symlinks and special
files, decompression bombs (declared AND actual sizes), binaries, vendored directories, and secret
scanning - a file with a credential is excluded from the seed (and so from every prompt), never
silently rewritten.
"""

import hashlib
import io
import ipaddress
import re
import shutil
import socket
import stat
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

from app.config import settings
from app.schemas.plan import validate_relative_path
from app.utils.redact import scan_secrets

SKIP_DIRS = frozenset(
    {".git", "node_modules", "__pycache__", ".venv", "venv", "env", "dist", "build", ".tox"}
)
_GIT_URL = re.compile(r"^https://[A-Za-z0-9.-]+(?::\d+)?/[A-Za-z0-9._~/-]+$")
MAX_RATIO = 200  # uncompressed/compressed per entry


class RepoImportError(Exception):
    """The repository was rejected (message is safe to show to the user)."""


@dataclass
class RepoImport:
    files: dict[str, str] = field(default_factory=dict)
    skipped: list[tuple[str, str]] = field(default_factory=list)
    secret_excluded: list[tuple[str, list[str]]] = field(default_factory=list)
    source_hash: str = ""

    def summary(self) -> dict[str, object]:
        reasons: dict[str, int] = {}
        for _, why in self.skipped:
            reasons[why] = reasons.get(why, 0) + 1
        return {
            "files": len(self.files),
            "skipped": reasons,
            "secret_excluded": [{"path": p, "kinds": k} for p, k in self.secret_excluded],
            "source_hash": self.source_hash,
        }


def _reject_unsafe(raw_path: str) -> None:
    path = raw_path.replace("\\", "/")
    if path.startswith("/") or ".." in PurePosixPath(path).parts or re.match(r"^[A-Za-z]:", path):
        raise RepoImportError(f"unsafe path in archive: {raw_path!r}")


class _Ingest:
    """Applies the per-file rules and running totals shared by the zip and git paths."""

    def __init__(self) -> None:
        self.result = RepoImport()
        self.total_bytes = 0
        self.seen = 0

    def add(self, raw_path: str, data: bytes) -> None:
        self.seen += 1
        limit = settings.repo_max_files
        if self.seen > limit * 5:
            raise RepoImportError(f"repository has too many entries (limit {limit * 5})")
        path = raw_path.replace("\\", "/")
        parts = PurePosixPath(path).parts
        _reject_unsafe(raw_path)
        if any(p in SKIP_DIRS for p in parts):
            self.result.skipped.append((path, "vendored or generated directory"))
            return
        if len(parts) > settings.repo_max_depth:
            self.result.skipped.append((path, "too deeply nested"))
            return
        if len(data) > settings.repo_max_file_bytes:
            self.result.skipped.append((path, "file too large"))
            return
        try:
            validate_relative_path(path)
        except ValueError:
            self.result.skipped.append((path, "path or extension not supported"))
            return
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            self.result.skipped.append((path, "not UTF-8 text"))
            return
        if "\x00" in text:
            self.result.skipped.append((path, "binary content"))
            return
        kinds = scan_secrets(path, text)
        if kinds:
            self.result.secret_excluded.append((path, kinds))
            return
        if len(self.result.files) >= settings.repo_max_files:
            raise RepoImportError(f"repository has more than {settings.repo_max_files} files")
        self.total_bytes += len(data)
        if self.total_bytes > settings.repo_max_total_bytes:
            raise RepoImportError("repository is larger than the allowed total size")
        self.result.files[path] = text.replace("\r\n", "\n")

    def finish(self) -> RepoImport:
        if not self.result.files:
            raise RepoImportError("no importable source files found in the repository")
        digest = hashlib.sha256()
        for p in sorted(self.result.files):
            digest.update(p.encode() + b"\0" + self.result.files[p].encode() + b"\0")
        self.result.source_hash = digest.hexdigest()
        return self.result


def _strip_common_root(names: list[str]) -> str:
    tops = {PurePosixPath(n.replace("\\", "/")).parts[0] for n in names if n.strip("/")}
    if len(tops) == 1 and all("/" in n.strip("/") for n in names if not n.endswith("/")):
        return tops.pop() + "/"
    return ""


def import_files(files: dict[str, str]) -> RepoImport:
    """Apply the same import rules (paths, sizes, secret scan) to files already in hand.

    Round 9 task chains seed a new task from another task's accepted code through this, so even
    our own generated files are checked exactly like an uploaded repository.
    """
    ingest = _Ingest()
    for path in sorted(files):
        ingest.add(path, files[path].encode("utf-8"))
    return ingest.finish()


def import_zip(blob: bytes) -> RepoImport:
    if len(blob) > settings.repo_max_archive_bytes:
        raise RepoImportError("archive is larger than the allowed upload size")
    try:
        zf = zipfile.ZipFile(io.BytesIO(blob))
    except zipfile.BadZipFile:
        raise RepoImportError("not a valid zip archive") from None
    with zf:
        infos = [i for i in zf.infolist() if not i.is_dir()]
        if len(infos) > settings.repo_max_files * 5:
            raise RepoImportError("archive contains too many entries")
        declared = sum(i.file_size for i in infos)
        if declared > settings.repo_max_total_bytes * 20:
            raise RepoImportError("archive expands to an unreasonable size")
        for info in infos:  # before any root stripping can hide a leading '..' or drive
            _reject_unsafe(info.filename)
        root = _strip_common_root([i.filename for i in infos])
        ingest = _Ingest()
        budget = settings.repo_max_total_bytes * 20  # actual bytes we are willing to inflate
        for info in infos:
            mode = info.external_attr >> 16
            name = info.filename.removeprefix(root)
            kind = stat.S_IFMT(mode)  # 0 when the archiver stored only permission bits
            if kind and kind != stat.S_IFREG:
                ingest.result.skipped.append((name, "symlink or special file"))
                continue
            if info.compress_size and info.file_size / info.compress_size > MAX_RATIO:
                raise RepoImportError(f"suspicious compression ratio: {name!r}")
            if info.file_size > settings.repo_max_file_bytes:
                ingest.result.skipped.append((name, "file too large"))
                continue
            with zf.open(info) as fh:  # headers can lie: cap the real read
                data = fh.read(settings.repo_max_file_bytes + 1)
            budget -= len(data)
            if budget < 0:
                raise RepoImportError("archive expands to an unreasonable size")
            ingest.add(name, data)
        return ingest.finish()


def validate_git_url_syntax(url: str) -> None:
    """Cheap check done at task creation; DNS/host checks happen again at clone time."""
    if not _GIT_URL.match(url) or "@" in urlsplit(url).netloc or ".." in url:
        raise RepoImportError("git URL must be a plain https URL without credentials")


def _check_git_url(url: str) -> None:
    if not _GIT_URL.match(url) or "@" in urlsplit(url).netloc or ".." in url:
        raise RepoImportError("git URL must be a plain https URL without credentials")
    host = urlsplit(url).hostname or ""
    if settings.repo_git_allowed_hosts:
        allowed = {h.strip().lower() for h in settings.repo_git_allowed_hosts.split(",") if h}
        if host.lower() not in allowed:
            raise RepoImportError("git host is not in the allowed list")
    try:
        addrs = {a[4][0] for a in socket.getaddrinfo(host, None)}
    except OSError:
        raise RepoImportError("git host could not be resolved") from None
    for addr in addrs:
        if not ipaddress.ip_address(addr.split("%")[0]).is_global:
            raise RepoImportError("git host resolves to a non-public address")


def import_git(url: str) -> RepoImport:
    """Shallow clone into a temp dir (no hooks, no submodules, no symlinks), then ingest as text."""
    _check_git_url(url)
    work = Path(tempfile.mkdtemp(prefix="lf-clone-"))
    try:
        empty_template = work / "tpl"
        empty_template.mkdir()
        dest = work / "repo"
        cmd = [
            "git", "-c", "protocol.allow=never", "-c", "protocol.https.allow=always",
            "-c", "core.symlinks=false", "-c", "core.hooksPath=" + str(empty_template),
            "-c", "transfer.fsckObjects=true", "-c", "submodule.recurse=false",
            "clone", "--depth=1", "--no-tags", "--single-branch", "--no-recurse-submodules",
            f"--template={empty_template}",
            f"--filter=blob:limit={settings.repo_max_file_bytes}",
            "--", url, str(dest),
        ]  # fmt: skip
        env = {"GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_NOSYSTEM": "1", "PATH": _path()}
        try:
            proc = subprocess.run(  # noqa: S603 - fixed argv, URL validated, no shell
                cmd, capture_output=True, text=True, timeout=settings.repo_git_timeout_seconds,
                env=env, check=False,
            )  # fmt: skip
        except subprocess.TimeoutExpired:
            raise RepoImportError("git clone timed out") from None
        except OSError:
            raise RepoImportError("git is not available on this server") from None
        if proc.returncode != 0:
            raise RepoImportError("git clone failed (repository missing or not public)")
        ingest = _Ingest()
        for p in sorted(dest.rglob("*")):
            rel = p.relative_to(dest).as_posix()
            if rel.split("/")[0] == ".git":
                continue
            if p.is_symlink() or p.is_junction():
                ingest.result.skipped.append((rel, "symlink or special file"))
            elif p.is_file():
                if p.stat().st_size > settings.repo_max_file_bytes:
                    ingest.result.skipped.append((rel, "file too large"))
                else:
                    ingest.add(rel, p.read_bytes())
        return ingest.finish()
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _path() -> str:
    import os

    return os.environ.get("PATH", "")
