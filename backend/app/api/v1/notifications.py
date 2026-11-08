"""In-app notifications and preferences (Phase 15). Per-user, so no organization context."""

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.database.models import Notification, User
from app.database.session import get_db
from app.services import notification_service

router = APIRouter(prefix="/notifications", tags=["notifications"])


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    kind: str
    title: str
    detail: dict[str, Any]
    org_id: uuid.UUID | None
    read_at: datetime | None
    created_at: datetime


class NotificationList(BaseModel):
    unread: int
    items: list[NotificationOut]


class Preferences(BaseModel):
    notify_email: bool


@router.get("", response_model=NotificationList)
def list_notifications(
    unread_only: bool = False,
    limit: int = Query(30, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> NotificationList:
    rows = notification_service.list_for(db, user, unread_only=unread_only, limit=limit)
    return NotificationList(
        unread=notification_service.unread_count(db, user),
        items=[NotificationOut.model_validate(r) for r in rows],
    )


@router.post("/read-all", status_code=status.HTTP_204_NO_CONTENT)
def read_all(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> None:
    notification_service.mark_read(db, user, None)


@router.post("/{notification_id}/read", status_code=status.HTTP_204_NO_CONTENT)
def read_one(
    notification_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    row = db.get(Notification, notification_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Notification not found")
    notification_service.mark_read(db, user, notification_id)


@router.get("/preferences", response_model=Preferences)
def get_preferences(user: User = Depends(get_current_user)) -> Preferences:
    return Preferences(notify_email=user.notify_email)


@router.put("/preferences", response_model=Preferences)
def set_preferences(
    body: Preferences, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> Preferences:
    user.notify_email = body.notify_email
    db.commit()
    return Preferences(notify_email=user.notify_email)
