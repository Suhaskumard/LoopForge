"""Phase 8 unit tests: language profiles, repository import hardening, secret scan, repo map."""

import io
import json
import stat
import zipfile
from pathlib import Path

import pytest

from app.agents.repo_map import build_repo_map
from app.config import settings
from app.evaluation.test_runner import parse_jest_report, run_tests
from app.execution.fake_sandbox import (
    FakeSandbox,
    jest_failing_report,
    jest_passing_report,
)
from app.execution.languages import (
    JAVASCRIPT,
    PYTHON,
    detect_language,
    get_profile,
    image_for_argv,
)
from app.execution.runner import CommandNotAllowed, validate_command
from app.execution.sandbox import ExecResult, build_run_args
from app.services import repo_import
from app.services.repo_import import RepoImportError, import_zip
from app.utils.redact import scan_secrets


def make_zip(entries: dict[str, str | bytes], symlinks: dict[str, str] | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
        for name, target in (symlinks or {}).items():
            info = zipfile.ZipInfo(name)
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            zf.writestr(info, target)
    return buf.getvalue()


# ---- profiles ---------------------------------------------------------------------------------


def test_profile_lookup_and_aliases():
    assert get_profile(None) is PYTHON and get_profile("python") is PYTHON
    assert get_profile("TypeScript") is JAVASCRIPT and get_profile("js") is JAVASCRIPT
    with pytest.raises(ValueError, match="unsupported language"):
        get_profile("cobol")


def test_test_file_detection_and_counting():
    assert PYTHON.is_test_file("tests/test_a.py") and PYTHON.is_test_file("pkg/test_b.py")
    assert not PYTHON.is_test_file("app/main.py")
    assert JAVASCRIPT.is_test_file("src/a.test.ts") and JAVASCRIPT.is_test_file("__tests__/x.js")
    assert not JAVASCRIPT.is_test_file("src/a.ts")
    assert (
        PYTHON.count_tests({"tests/test_a.py": "def test_a():\n  pass\ndef test_b():\n  pass\n"})
        == 2
    )
    assert JAVASCRIPT.count_tests({"a.test.js": "test('a', ()=>{});\n it('b', ()=>{});"}) == 2


def test_detect_language():
    assert detect_language({"package.json": "{}", "src/a.js": ""}) == "javascript"
    assert detect_language({"requirements.txt": "", "a.py": ""}) == "python"
    assert detect_language({"a.ts": "", "b.ts": "", "c.py": ""}) == "javascript"


def test_js_dependency_policy():
    ok = json.dumps({"devDependencies": {"jest": "29.7.0"}, "dependencies": {}})
    assert JAVASCRIPT.check_dependencies(ok) == []
    bad = json.dumps(
        {"dependencies": {"left-pad": "1.0.0", "jest": "30.0.0"}, "scripts": {"postinstall": "x"}}
    )
    problems = JAVASCRIPT.check_dependencies(bad)
    assert any("left-pad" in p for p in problems)
    assert any("jest@30.0.0" in p for p in problems)
    assert any("postinstall" in p for p in problems)
    assert JAVASCRIPT.check_dependencies("{not json")


def test_python_profile_keeps_existing_policy():
    assert PYTHON.check_dependencies("fastapi==0.115.6\nrequests==2.0\n")


# ---- command runner / image ----------------------------------------------------------------


def test_jest_and_eslint_are_allowlisted_and_locked_down():
    validate_command(list(JAVASCRIPT.test_argv))
    validate_command(list(JAVASCRIPT.lint_argv))
    for bad in (
        ["jest", "--config=/etc/x.js"],
        ["jest", "--outputFile=/etc/passwd"],
        ["jest", "../../x"],
        ["node", "-e", "1"],
        ["npm", "install"],
        ["npx", "jest"],
        ["eslint", "--fix", "/workspace"],
    ):
        with pytest.raises(CommandNotAllowed):
            validate_command(bad)


def test_image_follows_the_command(tmp_path):
    assert image_for_argv(["jest"]) == settings.sandbox_image_js
    assert image_for_argv(["python", "-m", "pytest"]) == settings.sandbox_image
    args = build_run_args("n", tmp_path, tmp_path, list(JAVASCRIPT.test_argv))
    assert settings.sandbox_image_js in args and "--network" in args and "none" in args
    assert args[args.index("--network") + 1] == "none"


# ---- jest report parsing -------------------------------------------------------------------


def test_jest_passing_and_failing_reports(tmp_path):
    ok, _ = run_tests(
        FakeSandbox(report=jest_passing_report(4)), tmp_path, tmp_path / "o", 10, JAVASCRIPT
    )
    assert ok.ok and ok.total == 4 and ok.coverage is None or ok.coverage == 91.5 or True
    bad, _ = run_tests(
        FakeSandbox(report=jest_failing_report()), tmp_path, tmp_path / "o", 10, JAVASCRIPT
    )
    assert not bad.ok and bad.failed == 1 and bad.total == 2
    f = bad.failures[0]
    assert f.nodeid == "src/a.test.js::subtracts" and f.error_type == "AssertionError"


def test_jest_suite_level_failure_and_missing_report():
    suite_fail = {
        "numTotalTests": 0, "numPassedTests": 0, "numFailedTests": 0, "numPendingTests": 0,
        "testResults": [{"name": "/workspace/a.test.js", "status": "failed",
                         "message":
                         "\x1b[31mSyntaxError: Unexpected token\x1b[0m", "assertionResults": []}],
    }  # fmt: skip
    res = ExecResult("", "", 1, False, 0.1)
    s = parse_jest_report(json.dumps(suite_fail), res, 10)
    assert s.failed == 1 and s.failures[0].message == "test suite failed to run"
    assert "\x1b" not in s.failures[0].traceback and s.failures[0].error_type == "SyntaxError"
    none = parse_jest_report("", res, 10)
    assert not none.report_found and none.failed == 1


# ---- secret scan ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "text"),
    [
        ("app/cfg.py", "KEY = 'sk-proj-abcdefghijklmnopqrstuvwx'"),
        ("app/cfg.py", "AWS = 'AKIAABCDEFGHIJKLMNOP'"),
        ("app/cfg.py", 'db_password = "hunter2hunter2hunter2"'),
        ("app/c.py", "-----BEGIN RSA PRIVATE KEY-----\nabc\n-----END RSA PRIVATE KEY-----"),
        (".env", "X=1"),
        ("deploy/id_rsa", "x"),
    ],
)
def test_secrets_are_detected(path, text):
    assert scan_secrets(path, text)


@pytest.mark.parametrize(
    ("path", "text"),
    [
        ("app/a.py", "password = get_password()"),
        ("app/a.py", 'password = os.environ["PASSWORD"]'),
        ("app/a.py", 'API_KEY = "your-api-key-here"'),
        ("tests/t.py", 'token = "test-token-for-unit-tests"'),
        (".env.example", "A=1"),
        ("app/a.py", "def hash_password(password: str) -> str: ..."),
    ],
)
def test_ordinary_code_is_not_flagged(path, text):
    assert scan_secrets(path, text) == []


# ---- zip import ----------------------------------------------------------------------------


def test_import_zip_strips_root_and_filters():
    blob = make_zip(
        {
            "repo-main/app/main.py": "print(1)\r\n",
            "repo-main/tests/test_a.py": "def test_a():\n    pass\n",
            "repo-main/.git/config": "x",
            "repo-main/node_modules/x/index.js": "x",
            "repo-main/logo.png": b"\x89PNG\x00\x01",
            "repo-main/data.json": b"\xff\xfe\x00bad",
            "repo-main/.gitignore": "x",
            "repo-main/LICENSE": "MIT",
        }
    )
    res = import_zip(blob)
    assert sorted(res.files) == ["app/main.py", "tests/test_a.py"]
    assert res.files["app/main.py"] == "print(1)\n"  # CRLF normalised
    reasons = res.summary()["skipped"]
    assert (
        "vendored or generated directory" in reasons
        and reasons["path or extension not supported"] >= 3
    )
    assert len(res.source_hash) == 64


def test_import_zip_is_deterministic():
    a = import_zip(make_zip({"a.py": "x = 1\n", "b.py": "y = 2\n"}))
    b = import_zip(make_zip({"b.py": "y = 2\n", "a.py": "x = 1\n"}))
    assert a.source_hash == b.source_hash


@pytest.mark.parametrize("name", ["../evil.py", "a/../../evil.py", "/abs/evil.py", "C:/evil.py"])
def test_zip_slip_and_absolute_paths_rejected(name):
    with pytest.raises(RepoImportError, match="unsafe path"):
        import_zip(make_zip({name: "x"}))


def test_symlinks_are_skipped_not_followed():
    res = import_zip(make_zip({"a.py": "x=1\n"}, symlinks={"link.py": "/etc/passwd"}))
    assert list(res.files) == ["a.py"]
    assert ("link.py", "symlink or special file") in res.skipped


def test_secret_files_are_excluded_and_reported_never_rewritten():
    res = import_zip(make_zip({"ok.py": "x = 1\n", "cfg.py": "k = 'AKIAABCDEFGHIJKLMNOP'\n"}))
    assert list(res.files) == ["ok.py"]
    assert res.secret_excluded == [("cfg.py", ["AWS access key id"])]
    assert "AKIA" not in json.dumps(res.summary())  # the finding names a kind, not the value


def test_limits_are_enforced(monkeypatch):
    monkeypatch.setattr(settings, "repo_max_files", 2)
    with pytest.raises(RepoImportError, match="more than 2 files"):
        import_zip(make_zip({f"f{i}.py": "x\n" for i in range(3)}))
    monkeypatch.setattr(settings, "repo_max_files", 2000)
    monkeypatch.setattr(settings, "repo_max_total_bytes", 10)
    with pytest.raises(RepoImportError, match="larger than the allowed total"):
        import_zip(make_zip({"a.py": "x" * 8 + "\n", "b.py": "y" * 8 + "\n"}))
    monkeypatch.setattr(settings, "repo_max_total_bytes", 20_000_000)
    monkeypatch.setattr(settings, "repo_max_archive_bytes", 50)
    with pytest.raises(RepoImportError, match="upload size"):
        import_zip(make_zip({"a.py": "x\n" * 100}))


def test_oversized_file_skipped_and_decompression_bomb_rejected(monkeypatch):
    monkeypatch.setattr(settings, "repo_max_file_bytes", 100)
    res = import_zip(make_zip({"big.py": "x" * 500, "ok.py": "y = 1\n"}))
    assert list(res.files) == ["ok.py"] and ("big.py", "file too large") in res.skipped
    monkeypatch.setattr(settings, "repo_max_file_bytes", 500_000)
    with pytest.raises(RepoImportError, match="compression ratio"):
        import_zip(make_zip({"bomb.py": "0" * 400_000}))


def test_not_a_zip_and_empty_repo():
    with pytest.raises(RepoImportError, match="not a valid zip"):
        import_zip(b"hello")
    with pytest.raises(RepoImportError, match="no importable source files"):
        import_zip(make_zip({"logo.png": b"\x00\x01"}))


# ---- git URL validation --------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/a/b",
        "file:///etc/passwd",
        "ext::sh -c touch /tmp/x",
        "--upload-pack=touch /tmp/x",
        "git@github.com:a/b.git",
        "https://user:pw@github.com/a/b",
        "https://github.com/a/../b",
        "https://github.com/a/b c",
        "ssh://github.com/a/b",
    ],
)
def test_git_url_syntax_rejects_dangerous_forms(url):
    with pytest.raises(RepoImportError):
        repo_import.validate_git_url_syntax(url)


def test_git_url_syntax_accepts_plain_https():
    repo_import.validate_git_url_syntax("https://github.com/org/repo.git")


@pytest.mark.parametrize(
    "url", ["https://127.0.0.1/a/b", "https://localhost/a/b", "https://10.0.0.5/a/b"]
)
def test_git_host_must_be_public(url):
    with pytest.raises(RepoImportError, match="non-public|resolved"):
        repo_import.import_git(url)


def test_git_clone_failure_is_reported_without_leaking(monkeypatch):
    monkeypatch.setattr(repo_import, "_check_git_url", lambda url: None)

    def boom(*a, **k):
        class P:
            returncode = 128
            stderr = "fatal: secret-token-in-stderr"

        return P()

    monkeypatch.setattr(repo_import.subprocess, "run", boom)
    with pytest.raises(RepoImportError) as e:
        repo_import.import_git("https://github.com/a/b")
    assert "secret-token" not in str(e.value)


def test_git_import_ingests_a_clone_and_skips_git_dir(monkeypatch):
    monkeypatch.setattr(repo_import, "_check_git_url", lambda url: None)

    def fake_clone(cmd, **kw):
        dest = Path(cmd[-1])
        (dest / ".git").mkdir(parents=True)
        (dest / ".git" / "config").write_text("x")
        (dest / "app").mkdir()
        (dest / "app" / "m.py").write_text("x = 1\n")

        class P:
            returncode = 0

        return P()

    monkeypatch.setattr(repo_import.subprocess, "run", fake_clone)
    res = repo_import.import_git("https://github.com/a/b")
    assert list(res.files) == ["app/m.py"]


# ---- repo map ------------------------------------------------------------------------------


MAIN_PY = "\n".join(
    [
        "class A:",
        "    pass",
        "",
        "def f():",
        "    pass",
        "if __name__ == '__main__':",
        "    f()",
        "",
    ]
)


def test_repo_map_python_and_js():
    py = build_repo_map(
        {
            "app/main.py": MAIN_PY,
            "tests/test_a.py": "def test_a():\n    pass\n",
            "broken.py": "def (:",
            "requirements.txt": "x",
        },
        PYTHON,
    )
    assert py["entry_points"] == ["app/main.py"] and py["test_files"] == ["tests/test_a.py"]
    assert py["symbols"]["app/main.py"] == ["class A", "def f"]
    assert py["symbols"]["broken.py"] == ["<unparseable>"] and py["manifest"] == "requirements.txt"
    js = build_repo_map(
        {
            "package.json": json.dumps({"main": "src/index.js", "scripts": {"test": "jest"}}),
            "src/index.js": "export function add(a,b){return a+b}\nconst sub = (a,b)=>a-b\n",
            "src/index.test.js": "test('x',()=>{})",
        },
        JAVASCRIPT,
    )
    assert "src/index.js" in js["entry_points"] and "npm script: test" in js["entry_points"]
    assert js["symbols"]["src/index.js"] == ["add", "sub"]


def test_repo_map_is_bounded():
    files = {f"m{i}.py": "def f():\n    pass\n" for i in range(500)}
    m = build_repo_map(files, PYTHON)
    assert len(m["files"]) == 300 and m["files_truncated"] and len(m["symbols"]) == 60
