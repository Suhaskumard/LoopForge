"""Webhook endpoints per organization (Phase 11, ADR-0018). Admin-only."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import Principal, require_org_role
from app.database.models import WebhookDelivery, WebhookEndpoint
from app.database.session import get_db
from app.schemas.integrations import DeliveryOut, WebhookCreate, WebhookCreated, WebhookOut
from app.services import audit_service, webhook_service

router = APIRouter(prefix="/orgs/{org_id}/webhooks", tags=["webhooks"])
admin = require_org_role("admin")


def _endpoint(db: Session, p: Principal, webhook_id: uuid.UUID) -> WebhookEndpoint:
    ep = db.get(WebhookEndpoint, webhook_id)
    if ep is None or ep.org_id != p.org_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Webhook not found")
    return ep


@router.get("", response_model=list[WebhookOut])
def list_webhooks(
    p: Principal = Depends(admin), db: Session = Depends(get_db)
) -> list[WebhookEndpoint]:
    return list(
        db.scalars(
            select(WebhookEndpoint)
            .where(WebhookEndpoint.org_id == p.org_id)
            .order_by(WebhookEndpoint.created_at)
        )
    )


@router.post("", response_model=WebhookCreated, status_code=status.HTTP_201_CREATED)
def create_webhook(
    data: WebhookCreate,
    request: Request,
    p: Principal = Depends(admin),
    db: Session = Depends(get_db),
) -> WebhookCreated:
    try:
        ep = webhook_service.create_endpoint(db, p.org_id, data.url, data.events, data.format)
    except webhook_service.WebhookUrlError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None
    audit_service.record(
        db,
        org_id=p.org_id,
        actor_id=p.user.id,
        action="webhook.create",
        target_type="webhook",
        target_id=ep.id,
        detail={"url": ep.url},
        request=request,
    )
    return WebhookCreated(**WebhookOut.model_validate(ep).model_dump(), secret=ep.secret)


@router.delete("/{webhook_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_webhook(
    webhook_id: uuid.UUID,
    request: Request,
    p: Principal = Depends(admin),
    db: Session = Depends(get_db),
) -> Response:
    ep = _endpoint(db, p, webhook_id)
    ep.active = False  # deliveries keep their history
    db.commit()
    audit_service.record(
        db,
        org_id=p.org_id,
        actor_id=p.user.id,
        action="webhook.delete",
        target_type="webhook",
        target_id=ep.id,
        request=request,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{webhook_id}/test", response_model=DeliveryOut)
def test_webhook(
    webhook_id: uuid.UUID, p: Principal = Depends(admin), db: Session = Depends(get_db)
) -> WebhookDelivery:
    ep = _endpoint(db, p, webhook_id)
    delivery = WebhookDelivery(
        endpoint_id=ep.id,
        org_id=p.org_id,
        event="ping",
        payload={"id": str(uuid.uuid4()), "event": "ping", "data": {"hello": "world"}},
    )
    db.add(delivery)
    db.commit()
    return webhook_service.deliver(db, delivery)


@router.get("/{webhook_id}/deliveries", response_model=list[DeliveryOut])
def deliveries(
    webhook_id: uuid.UUID, p: Principal = Depends(admin), db: Session = Depends(get_db)
) -> list[WebhookDelivery]:
    ep = _endpoint(db, p, webhook_id)
    return list(
        db.scalars(
            select(WebhookDelivery)
            .where(WebhookDelivery.endpoint_id == ep.id)
            .order_by(WebhookDelivery.created_at.desc())
            .limit(50)
        )
    )
