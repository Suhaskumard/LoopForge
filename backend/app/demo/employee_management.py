"""Canned planner/builder outputs for the spec §15.2 demo task.

Used by the deterministic FakeLLMClient (tests, `LLM_PROVIDER=fake`, gate scripts). The generated
project is real, working code so later phases can execute and test it.
"""

from typing import Any

from app.schemas.plan import BuilderOutput, FileChange, ProjectPlan

DEMO_REQUIREMENT = (
    "Develop a FastAPI-based employee management system with authentication, "
    "CRUD endpoints, input validation and unit tests."
)

DEPENDENCIES = [
    "fastapi==0.115.6",
    "uvicorn==0.34.0",
    "pydantic==2.10.3",
    "pytest==8.3.4",
    "httpx==0.28.1",
]

PLAN: dict[str, Any] = {
    "project_name": "employee_management",
    "framework": "FastAPI",
    "requirements": [
        {
            "req_id": "REQ-001",
            "description": "User registration and login with token auth",
            "type": "security",
            "priority": "critical",
        },
        {
            "req_id": "REQ-002",
            "description": "Create an employee",
            "type": "functional",
            "priority": "high",
        },
        {
            "req_id": "REQ-003",
            "description": "Read one or all employees",
            "type": "functional",
            "priority": "high",
        },
        {
            "req_id": "REQ-004",
            "description": "Update an employee",
            "type": "functional",
            "priority": "high",
        },
        {
            "req_id": "REQ-005",
            "description": "Delete an employee",
            "type": "functional",
            "priority": "medium",
        },
        {
            "req_id": "REQ-006",
            "description": "Reject invalid input with HTTP 422",
            "type": "security",
            "priority": "high",
        },
        {
            "req_id": "REQ-007",
            "description": "Unit tests covering every endpoint",
            "type": "non_functional",
            "priority": "high",
        },
    ],
    "acceptance_criteria": [
        "All API endpoints respond correctly",
        "Authentication is enforced",
        "Invalid input is rejected",
        "All required tests pass",
    ],
    "files": [
        {"path": "app/__init__.py", "purpose": "Package marker"},
        {
            "path": "app/main.py",
            "purpose": "FastAPI application wiring",
            "implements": ["REQ-001", "REQ-002"],
        },
        {
            "path": "app/auth.py",
            "purpose": "Registration, login and token dependency",
            "implements": ["REQ-001"],
        },
        {"path": "app/models.py", "purpose": "Employee domain model", "implements": ["REQ-002"]},
        {
            "path": "app/schemas.py",
            "purpose": "Request/response validation schemas",
            "implements": ["REQ-006"],
        },
        {
            "path": "app/routes.py",
            "purpose": "Employee CRUD endpoints",
            "implements": ["REQ-002", "REQ-003", "REQ-004", "REQ-005"],
        },
        {"path": "tests/__init__.py", "purpose": "Package marker"},
        {"path": "tests/test_routes.py", "purpose": "Endpoint tests", "implements": ["REQ-007"]},
        {"path": "pytest.ini", "purpose": "Pytest configuration"},
        {"path": "requirements.txt", "purpose": "Pinned dependencies"},
    ],
    "dependencies": DEPENDENCIES,
}

_AUTH = """import hashlib
import hmac
import secrets

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.schemas import Credentials, TokenOut

router = APIRouter(prefix="/auth", tags=["auth"])
bearer = HTTPBearer(auto_error=False)

_USERS: dict[str, tuple[bytes, bytes]] = {}
_TOKENS: dict[str, str] = {}


def _hash(password: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100_000)


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(data: Credentials) -> dict[str, str]:
    if data.username in _USERS:
        raise HTTPException(status.HTTP_409_CONFLICT, "User already exists")
    salt = secrets.token_bytes(16)
    _USERS[data.username] = (salt, _hash(data.password, salt))
    return {"username": data.username}


@router.post("/login", response_model=TokenOut)
def login(data: Credentials) -> TokenOut:
    record = _USERS.get(data.username)
    if record is None or not hmac.compare_digest(record[1], _hash(data.password, record[0])):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
    token = secrets.token_urlsafe(24)
    _TOKENS[token] = data.username
    return TokenOut(access_token=token)


def require_user(creds: HTTPAuthorizationCredentials | None = Depends(bearer)) -> str:
    if creds is None or creds.credentials not in _TOKENS:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    return _TOKENS[creds.credentials]


def reset() -> None:
    _USERS.clear()
    _TOKENS.clear()
"""

_MODELS = """from dataclasses import dataclass


@dataclass
class Employee:
    id: int
    name: str
    email: str
    department: str
"""

_SCHEMAS = """from pydantic import BaseModel, Field


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=8, max_length=128)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class EmployeeIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    email: str = Field(pattern=r"^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$")
    department: str = Field(min_length=1, max_length=100)


class EmployeeOut(EmployeeIn):
    id: int
"""

_ROUTES = """from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.auth import require_user
from app.models import Employee
from app.schemas import EmployeeIn, EmployeeOut

router = APIRouter(prefix="/employees", tags=["employees"], dependencies=[Depends(require_user)])

_STORE: dict[int, Employee] = {}
_next_id = 1


def reset() -> None:
    global _next_id
    _STORE.clear()
    _next_id = 1


@router.post("", response_model=EmployeeOut, status_code=status.HTTP_201_CREATED)
def create(data: EmployeeIn) -> Employee:
    global _next_id
    employee = Employee(id=_next_id, **data.model_dump())
    _STORE[employee.id] = employee
    _next_id += 1
    return employee


@router.get("", response_model=list[EmployeeOut])
def list_all() -> list[Employee]:
    return list(_STORE.values())


@router.get("/{employee_id}", response_model=EmployeeOut)
def get_one(employee_id: int) -> Employee:
    employee = _STORE.get(employee_id)
    if employee is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Employee not found")
    return employee


@router.put("/{employee_id}", response_model=EmployeeOut)
def update(employee_id: int, data: EmployeeIn) -> Employee:
    employee = get_one(employee_id)
    employee.name, employee.email, employee.department = data.name, data.email, data.department
    return employee


@router.delete("/{employee_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete(employee_id: int) -> Response:
    get_one(employee_id)
    del _STORE[employee_id]
    return Response(status_code=status.HTTP_204_NO_CONTENT)
"""

_MAIN = """from fastapi import FastAPI

from app import auth, routes

app = FastAPI(title="Employee Management")
app.include_router(auth.router)
app.include_router(routes.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
"""

_TESTS = """import pytest
from fastapi.testclient import TestClient

from app import auth, routes
from app.main import app

EMPLOYEE = {"name": "Ada Lovelace", "email": "ada@example.com", "department": "Engineering"}


@pytest.fixture
def client() -> TestClient:
    auth.reset()
    routes.reset()
    return TestClient(app)


@pytest.fixture
def headers(client: TestClient) -> dict[str, str]:
    creds = {"username": "alice", "password": "correct-horse"}
    assert client.post("/auth/register", json=creds).status_code == 201
    token = client.post("/auth/login", json=creds).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_register_conflict_and_bad_login(client: TestClient) -> None:
    creds = {"username": "bob12", "password": "password123"}
    assert client.post("/auth/register", json=creds).status_code == 201
    assert client.post("/auth/register", json=creds).status_code == 409
    bad = {"username": "bob12", "password": "wrong-password"}
    assert client.post("/auth/login", json=bad).status_code == 401


def test_authentication_is_enforced(client: TestClient) -> None:
    assert client.get("/employees").status_code == 401
    assert client.post("/employees", json=EMPLOYEE).status_code == 401
    bad = {"Authorization": "Bearer nope"}
    assert client.get("/employees", headers=bad).status_code == 401


def test_create_and_read(client: TestClient, headers: dict[str, str]) -> None:
    created = client.post("/employees", json=EMPLOYEE, headers=headers)
    assert created.status_code == 201
    emp_id = created.json()["id"]
    assert client.get(f"/employees/{emp_id}", headers=headers).json()["name"] == "Ada Lovelace"
    assert len(client.get("/employees", headers=headers).json()) == 1


def test_update(client: TestClient, headers: dict[str, str]) -> None:
    emp_id = client.post("/employees", json=EMPLOYEE, headers=headers).json()["id"]
    changed = {**EMPLOYEE, "department": "Research"}
    updated = client.put(f"/employees/{emp_id}", json=changed, headers=headers)
    assert updated.status_code == 200
    assert updated.json()["department"] == "Research"


def test_delete(client: TestClient, headers: dict[str, str]) -> None:
    emp_id = client.post("/employees", json=EMPLOYEE, headers=headers).json()["id"]
    assert client.delete(f"/employees/{emp_id}", headers=headers).status_code == 204
    assert client.get(f"/employees/{emp_id}", headers=headers).status_code == 404


def test_not_found(client: TestClient, headers: dict[str, str]) -> None:
    assert client.get("/employees/999", headers=headers).status_code == 404
    assert client.put("/employees/999", json=EMPLOYEE, headers=headers).status_code == 404
    assert client.delete("/employees/999", headers=headers).status_code == 404


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {**EMPLOYEE, "name": ""},
        {**EMPLOYEE, "email": "not-an-email"},
        {"name": "X", "email": "x@example.com"},
    ],
)
def test_invalid_input_rejected(
    client: TestClient, headers: dict[str, str], payload: dict[str, str]
) -> None:
    assert client.post("/employees", json=payload, headers=headers).status_code == 422
"""

_PYTEST_INI = "[pytest]\npythonpath = .\ntestpaths = tests\n"


def builder_output() -> BuilderOutput:
    files = {
        "app/__init__.py": "",
        "app/main.py": _MAIN,
        "app/auth.py": _AUTH,
        "app/models.py": _MODELS,
        "app/schemas.py": _SCHEMAS,
        "app/routes.py": _ROUTES,
        "tests/__init__.py": "",
        "tests/test_routes.py": _TESTS,
        "pytest.ini": _PYTEST_INI,
        "requirements.txt": "\n".join(DEPENDENCIES) + "\n",
    }
    return BuilderOutput(files=[FileChange(path=p, content=c) for p, c in files.items()])


def demo_plan() -> ProjectPlan:
    return ProjectPlan.model_validate(PLAN)


def demo_responses() -> list[ProjectPlan | BuilderOutput]:
    """Planner output followed by Builder output, in call order."""
    return [demo_plan(), builder_output()]
