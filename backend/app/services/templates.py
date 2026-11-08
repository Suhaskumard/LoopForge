"""Starter task templates (Phase 15). Static on purpose: a template is just a good prompt."""

from typing import TypedDict


class Template(TypedDict):
    id: str
    name: str
    description: str
    language: str
    requirement: str
    acceptance_criteria: list[str]


TEMPLATES: list[Template] = [
    {
        "id": "crud-api",
        "name": "CRUD REST API",
        "description": "A small FastAPI service with create/read/update/delete and tests.",
        "language": "python",
        "requirement": (
            "Build a FastAPI service that manages 'items' (id, name, price) in memory with "
            "endpoints to create, list, fetch, update and delete items. Validate input and "
            "return proper 404 and 422 responses. Include pytest tests for every endpoint."
        ),
        "acceptance_criteria": [
            "All five endpoints exist and return correct status codes",
            "Invalid input is rejected with 422",
            "Unknown ids return 404",
        ],
    },
    {
        "id": "auth-service",
        "name": "Authentication service",
        "description": "Register/login with hashed passwords and signed tokens.",
        "language": "python",
        "requirement": (
            "Build a small authentication module: register users with a bcrypt-hashed password, "
            "log in to receive a signed JWT, and verify a token. Reject duplicate emails and "
            "wrong passwords. Never store or log plaintext passwords. Include pytest tests."
        ),
        "acceptance_criteria": [
            "Passwords are stored only as hashes",
            "Wrong password and unknown user give the same error",
            "Expired or tampered tokens are rejected",
        ],
    },
    {
        "id": "validation-library",
        "name": "Data-validation library",
        "description": "A reusable library that validates records against a schema.",
        "language": "python",
        "requirement": (
            "Write a Python library that validates dictionaries against a declarative schema "
            "(required fields, types, min/max, regex, enums) and returns every error with its "
            "field path rather than stopping at the first. Include pytest tests."
        ),
        "acceptance_criteria": [
            "All errors are reported, each with a field path",
            "Nested objects and lists are supported",
            "Valid data returns no errors",
        ],
    },
]


def by_id(template_id: str) -> Template | None:
    return next((t for t in TEMPLATES if t["id"] == template_id), None)
