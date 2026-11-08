"""OracleLLM: a deterministic stand-in "model" that answers from the task's reference solution.

!!! Its results are SYNTHETIC. It exists to exercise the harness (task loading, loop, hidden-test
evaluation, statistics) with a real pytest execution and no API key. Any number produced with it is
a harness check, never a measurement of LoopForge or of any model.

Behaviour per trial (`mode`):
  perfect  - first build is the reference solution
  flawed   - first build crashes on import; a repair restores the reference file
  hopeless - first build crashes on import and every repair returns the same broken file
"""

import json
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

from app.schemas.loop import (
    CriterionAssessment,
    RepairOutput,
    RequirementCoverage,
    ReviewOutput,
)
from app.schemas.plan import (
    BuilderOutput,
    FileChange,
    PlannedFile,
    ProjectPlan,
    RequirementItem,
)
from app.services.llm_client import LLMResult
from app.utils.token_tracker import Usage

T = TypeVar("T", bound=BaseModel)

REQUIREMENTS_TXT = (
    "fastapi==0.115.6\nuvicorn==0.34.0\npydantic==2.10.3\npytest==8.3.4\nhttpx==0.28.1\n"
    "pyjwt==2.10.1\nbcrypt==4.2.1\n"
)
def smoke_test(modules: list[str]) -> str:
    """The project's own (weak) test: every app module imports. Hidden tests do much more."""
    return (
        "import importlib\n\nimport pytest\n\n\n"
        f"@pytest.mark.parametrize('name', {modules!r})\n"
        "def test_module_imports(name):\n"
        "    assert importlib.import_module(name) is not None\n"
    )


BREAK = "\nraise RuntimeError('injected defect: module crashes on import')\n"
MODES = ("perfect", "flawed", "hopeless")


class OracleLLM:
    def __init__(self, task_dir: Path, mode: str) -> None:
        assert mode in MODES
        meta = json.loads((task_dir / "task.json").read_text(encoding="utf-8"))
        self.criteria: list[str] = meta["acceptance_criteria"]
        self.mode = mode
        self.reference = {
            p.relative_to(task_dir / "reference").as_posix(): p.read_text(encoding="utf-8")
            for p in sorted((task_dir / "reference").rglob("*.py"))
        }
        self.reference["requirements.txt"] = REQUIREMENTS_TXT
        mods = [p[:-3].replace("/", ".") for p in self.reference if p.startswith("app/") and p != "app/__init__.py"]
        self.reference["tests/test_smoke.py"] = smoke_test(mods)
        # break the module the hidden tests actually exercise
        self.target = "app/validators.py" if "app/validators.py" in self.reference else "app/main.py"
        self.calls: list[str] = []

    # -- model answers ----------------------------------------------------------------------
    def _plan(self) -> ProjectPlan:
        req_ids = ["REQ-001", "REQ-002"]
        return ProjectPlan(
            project_name="benchmark_project",
            requirements=[
                RequirementItem(req_id=req_ids[0], description="Implement the specified behaviour",
                                type="functional", priority="critical"),
                RequirementItem(req_id=req_ids[1], description="Reject invalid input safely",
                                type="functional", priority="high"),
            ],
            acceptance_criteria=self.criteria,
            files=[
                PlannedFile(path=p, purpose=f"{p} of the solution",
                            implements=req_ids if p.startswith("app/") and p.endswith(".py") else [])
                for p in self.reference
            ],
            dependencies=[line for line in REQUIREMENTS_TXT.splitlines()],
        )  # fmt: skip

    def _build(self) -> BuilderOutput:
        files = dict(self.reference)
        if self.mode != "perfect":
            files[self.target] = files[self.target] + BREAK
        return BuilderOutput(files=[FileChange(path=p, content=c) for p, c in files.items()])

    def _repair(self) -> RepairOutput:
        broken = self.mode == "hopeless"
        content = self.reference[self.target] + (BREAK if broken else "")
        return RepairOutput(
            root_cause="The module raises on import" if not broken else "Not sure",
            explanation="Remove the crashing statement" if not broken else "Tried again",
            changes=[FileChange(path=self.target, content=content, action="modify")],
        )

    def _review(self) -> ReviewOutput:
        return ReviewOutput(
            critical_issues=[],
            acceptance_criteria=[
                CriterionAssessment(criterion=c, met=True, evidence="covered by hidden-style tests")
                for c in self.criteria
            ],
            requirement_coverage=[
                RequirementCoverage(req_id="REQ-001", covered=True),
                RequirementCoverage(req_id="REQ-002", covered=True),
            ],
            maintainability_notes=[],
            quality_score=0.9,
        )

    # -- LLMClient protocol -----------------------------------------------------------------
    def complete_json(self, *, system: str, user: str, response_model: type[T]) -> LLMResult[T]:
        name = response_model.__name__
        self.calls.append(name)
        answers: dict[str, Any] = {
            "ProjectPlan": self._plan,
            "BuilderOutput": self._build,
            "RepairOutput": self._repair,
            "ReviewOutput": self._review,
        }
        out = answers[name]()
        raw = out.model_dump_json()
        usage = Usage(max(1, (len(system) + len(user)) // 4), max(1, len(raw) // 4))
        return LLMResult(response_model.model_validate_json(raw), usage)
