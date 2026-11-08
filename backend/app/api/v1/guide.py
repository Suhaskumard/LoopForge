"""Guided experience (Phase 15): task templates and the onboarding checklist."""

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.database.models import ApprovalRequest, Membership, Task, User
from app.database.session import get_db
from app.services import org_service
from app.services.templates import TEMPLATES

router = APIRouter(tags=["guide"])


class TemplateOut(BaseModel):
    id: str
    name: str
    description: str
    language: str
    requirement: str
    acceptance_criteria: list[str]


class Step(BaseModel):
    id: str
    title: str
    done: bool
    hint: str


class Onboarding(BaseModel):
    steps: list[Step]
    complete: bool


@router.get("/templates", response_model=list[TemplateOut])
def templates(_: User = Depends(get_current_user)) -> list[Any]:
    return list(TEMPLATES)


@router.get("/me/onboarding", response_model=Onboarding)
def onboarding(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Onboarding:
    """Derived from stored facts every time, so it can never drift from reality."""
    org_ids = [m.org_id for m in org_service.memberships_of(db, user.id)]
    tasks = db.scalar(select(func.count()).select_from(Task).where(Task.created_by == user.id)) or 0
    finished = (
        db.scalar(
            select(func.count())
            .select_from(Task)
            .where(Task.created_by == user.id, Task.status == "COMPLETED")
        )
        or 0
    )
    decided = (
        db.scalar(
            select(func.count())
            .select_from(ApprovalRequest)
            .where(ApprovalRequest.decided_by == user.id)
        )
        or 0
    )
    teammates = (
        db.scalar(
            select(func.count())
            .select_from(Membership)
            .where(Membership.org_id.in_(org_ids), Membership.user_id != user.id)
        )
        or 0
    )
    steps = [
        Step(id="verify_email", title="Verify your email", done=user.email_verified_at is not None,
             hint="Open the link we emailed you."),
        Step(id="first_task", title="Create your first task", done=tasks > 0,
             hint="Pick a template to start quickly."),
        Step(id="first_result", title="Get an accepted result", done=finished > 0,
             hint="Start the task and watch the loop."),
        Step(id="first_decision", title="Review an approval", done=decided > 0,
             hint="Enable plan approval on a task to try the gate."),
        Step(id="invite_teammate", title="Invite a teammate", done=teammates > 0,
             hint="Admins can invite by email from the Admin page."),
    ]  # fmt: skip
    return Onboarding(steps=steps, complete=all(s.done for s in steps))
