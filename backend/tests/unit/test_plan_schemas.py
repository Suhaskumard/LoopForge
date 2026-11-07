import copy

import pytest
from pydantic import ValidationError

from app.demo.employee_management import PLAN, builder_output, demo_plan
from app.schemas.plan import (
    MAX_FILE_CHARS,
    BuilderOutput,
    FileChange,
    ProjectPlan,
    validate_relative_path,
)

BAD_PATHS = [
    "",
    "../x.py",
    "a/../../x.py",
    "/etc/x.py",
    "C:/x.py",
    "c:x.py",
    "C:\\x.py",
    "\\\\srv\\share\\x.py",
    ".git/config.py",
    "a/.hidden.py",
    ".env.txt",
    "a//b.py",
    "a/./b.py",
    "evil.exe",
    "script.sh",
    "noextension",
    "a\x00b.py",
    "x" * 201 + ".py",
]
GOOD_PATHS = ["app/main.py", "requirements.txt", "tests/test_x.py", "pytest.ini", "README.md"]


@pytest.mark.parametrize("path", BAD_PATHS)
def test_unsafe_paths_rejected(path):
    with pytest.raises(ValueError):
        validate_relative_path(path)
    with pytest.raises(ValidationError):
        FileChange(path=path, content="x")


@pytest.mark.parametrize("path", GOOD_PATHS)
def test_safe_paths_accepted(path):
    assert validate_relative_path(path) == path


def test_demo_plan_is_valid_and_complete():
    plan = demo_plan()
    assert len(plan.requirements) == 7 and plan.acceptance_criteria
    assert {f.path for f in plan.files} == {f.path for f in builder_output().files}


def _plan(**mutations):
    data = copy.deepcopy(PLAN)
    data.update(mutations)
    return data


def test_plan_requires_requirements_txt():
    files = [f for f in PLAN["files"] if f["path"] != "requirements.txt"]
    with pytest.raises(ValidationError, match="requirements.txt"):
        ProjectPlan.model_validate(_plan(files=files))


def test_plan_rejects_duplicate_ids_paths_and_unknown_refs():
    reqs = PLAN["requirements"] + [PLAN["requirements"][0]]
    with pytest.raises(ValidationError, match="duplicate requirement"):
        ProjectPlan.model_validate(_plan(requirements=reqs))
    files = PLAN["files"] + [PLAN["files"][0]]
    with pytest.raises(ValidationError, match="duplicate file"):
        ProjectPlan.model_validate(_plan(files=files))
    bad = copy.deepcopy(PLAN["files"])
    bad[1]["implements"] = ["REQ-999"]
    with pytest.raises(ValidationError, match="unknown requirement"):
        ProjectPlan.model_validate(_plan(files=bad))


@pytest.mark.parametrize(
    "mutation",
    [
        {"project_name": "Employee-App"},
        {"project_name": ""},
        {"framework": "Django"},
        {"acceptance_criteria": []},
        {"acceptance_criteria": ["  "]},
        {"requirements": []},
        {"dependencies": ["fastapi>=1.0"]},
        {"dependencies": ["git+https://evil.example/x.git"]},
        {"dependencies": ["x; rm -rf /"]},
        {"surprise": "field"},
    ],
)
def test_plan_rejects_bad_fields(mutation):
    with pytest.raises(ValidationError):
        ProjectPlan.model_validate(_plan(**mutation))


def test_requirement_id_format_enforced():
    reqs = copy.deepcopy(PLAN["requirements"])
    reqs[0]["req_id"] = "REQ-1"
    with pytest.raises(ValidationError, match="REQ-001"):
        ProjectPlan.model_validate(_plan(requirements=reqs))


def test_builder_output_rules():
    ok = builder_output()
    assert len(ok.files) == 10
    with pytest.raises(ValidationError, match="duplicate"):
        BuilderOutput(files=[ok.files[0], ok.files[0]])
    no_req = [f for f in ok.files if f.path != "requirements.txt"]
    with pytest.raises(ValidationError, match="requirements.txt"):
        BuilderOutput(files=no_req)
    with pytest.raises(ValidationError):
        FileChange(path="a.py", content="x" * (MAX_FILE_CHARS + 1))
    big = [FileChange(path=f"f{i}.py", content="x" * 190_000) for i in range(6)]
    big.append(FileChange(path="requirements.txt", content=""))
    with pytest.raises(ValidationError, match="too large"):
        BuilderOutput(files=big)
    with pytest.raises(ValidationError):
        BuilderOutput.model_validate({"files": [{"path": "a.py", "content": "", "x": 1}]})
