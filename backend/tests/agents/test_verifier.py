from app.agents import verifier
from app.database.models import TestResult
from app.execution.fake_sandbox import FakeSandbox
from app.services import workspace


def _write(ctx, files):
    base = workspace.iteration_dir(ctx.task.id, ctx.iteration.iteration_number)
    for rel, text in files.items():
        (base / rel).parent.mkdir(parents=True, exist_ok=True)
        (base / rel).write_text(text, encoding="utf-8")


def test_unapproved_dependency_blocks_execution(ctx, db):
    _write(ctx, {"requirements.txt": "fastapi==0.115.6\nrequests==2.32.0\n"})
    sb = FakeSandbox()
    summary = verifier.run(ctx, sb)
    assert sb.calls == []  # never reached the sandbox
    assert not summary.ok and "not approved: requests" in summary.failures[0].message
    row = db.query(TestResult).one()
    assert row.failed == 1 and row.details["blocked"] == "dependency policy"


def test_clean_requirements_execute(ctx, db):
    _write(ctx, {"requirements.txt": "pytest==8.3.4\n"})
    summary = verifier.run(ctx, FakeSandbox())
    assert summary.ok and db.query(TestResult).one().passed == 3
