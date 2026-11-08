"""Run the real API with a scripted loop so the dashboard can be tried with no API key or Docker.

Every task you start plays the Phase 4 story: the Builder ships an injected defect, the tests
fail, the Repair agent fixes it, the full suite is re-run and the task completes. Calls are
slowed down (DEMO_DELAY seconds) so the live view is watchable.

    python scripts/dev_demo_server.py            # http://localhost:8000  (API + WebSocket)
    cd frontend && npm run dev                   # http://localhost:5173  (the dashboard)

Demo data lives in a temp directory; nothing touches your real database or workspaces.
"""

import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

work = Path(tempfile.mkdtemp(prefix="loopforge_demo_ui_"))
os.environ.update(
    {
        "DATABASE_URL": f"sqlite:///{work / 'demo.db'}",
        "WORKSPACE_ROOT": str(work / "workspaces"),
        "LLM_PROVIDER": "fake",
        "SANDBOX_BACKEND": "fake",
        "ENVIRONMENT": "development",
    }
)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import uvicorn  # noqa: E402

from app.api.dependencies import get_llm, get_sandbox  # noqa: E402
from app.database.models import Base  # noqa: E402
from app.database.session import engine  # noqa: E402
from app.demo.employee_management import (  # noqa: E402
    defective_builder_output,
    demo_plan,
    failing_update_report,
    passing_report_for_demo,
    repair_output,
    review_output,
)
from app.execution.fake_sandbox import ScriptedSandbox  # noqa: E402
from app.execution.sandbox import ExecResult  # noqa: E402
from app.main import app  # noqa: E402
from app.schemas.report import ReadmeOutput  # noqa: E402
from app.services.llm_client import FakeLLMClient, LLMResult  # noqa: E402

DELAY = float(os.environ.get("DEMO_DELAY", "1.5"))


class SlowLLM(FakeLLMClient):
    def complete_json(self, **kwargs: Any) -> LLMResult[Any]:
        time.sleep(DELAY)
        return super().complete_json(**kwargs)


class SlowSandbox(ScriptedSandbox):
    def run(self, workspace: Path, out_dir: Path, argv: list[str], timeout: int) -> ExecResult:
        time.sleep(DELAY)
        return super().run(workspace, out_dir, argv, timeout)


# DEMO_MODE=never-pass: every iteration fails with a *different* failing test, so the Decision Engine's
# repeat detector does not stop the loop early and the iteration limit (set it to 10 in the UI) is what ends it.
NEVER_PASS = os.environ.get("DEMO_MODE") == "never-pass"
NEVER_PASS_RUNS = 12


def varied_failing_report(n: int) -> dict[str, Any]:
    rep = failing_update_report()
    rep["tests"][1]["nodeid"] = f"tests/test_routes.py::test_update_and_delete_case_{n}"
    return rep


def fresh_llm() -> FakeLLMClient:
    readme = ReadmeOutput(
        content="# Employee API\n\nRun `uvicorn app.main:app`; run the tests with `pytest`.\n"
    )
    if NEVER_PASS:
        return SlowLLM().queue(
            demo_plan(),
            defective_builder_output(),
            *[repair_output() for _ in range(NEVER_PASS_RUNS)],
            readme,
        )
    return SlowLLM().queue(
        demo_plan(), defective_builder_output(), repair_output(), review_output(), readme
    )


def fresh_sandbox() -> ScriptedSandbox:
    if NEVER_PASS:
        return SlowSandbox([varied_failing_report(i) for i in range(1, NEVER_PASS_RUNS + 1)])
    return SlowSandbox([failing_update_report(), passing_report_for_demo()])


app.dependency_overrides[get_llm] = fresh_llm
app.dependency_overrides[get_sandbox] = fresh_sandbox

# E2E=1 (Playwright): mail goes to an in-process outbox that the browser tests read over HTTP. This
# route exists ONLY in this demo server, never in the real app.
if os.environ.get("E2E") == "1":
    from app.config import settings  # noqa: E402
    from app.services import mail_service  # noqa: E402

    settings.mail_backend = "memory"
    settings.login_max_attempts = 1000  # tests sign in many times from one address

    @app.get("/__test__/outbox")
    def _outbox(to: str | None = None) -> list[dict[str, str]]:
        return [
            {"to": m.to, "subject": m.subject, "body": m.body}
            for m in mail_service.outbox
            if to is None or m.to == to
        ]

if __name__ == "__main__":
    Base.metadata.create_all(engine)
    print(f"demo data in {work}")
    uvicorn.run(
        app, host="127.0.0.1", port=int(os.environ.get("PORT", "8000")), log_level="warning"
    )
