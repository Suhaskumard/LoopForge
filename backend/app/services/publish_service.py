"""Open a pull request from a finished task, behind a human approval (Phase 11, ADR-0018).

Invariant: `push` talks to the git provider only for a row that is `approved` in the database at
that moment (re-read under a lock, like the loop gate in ADR-0013), and an approved row is
pushed at most once. Requesting, deciding and pushing each leave an `audit_log` entry.
"""

import uuid
from datetime import datetime, timezone

from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database.models import (
    Iteration,
    Membership,
    OrgIntegration,
    PublishRequest,
    Task,
)
from app.services import audit_service, github_service, report_service, webhook_service, workspace
from app.services.github_service import GitHubClient, GitHubError
from app.utils.redact import scan_secrets
from app.utils.security import decrypt_secret


class PublishError(Exception):
    """Refused; `status_code` maps to the HTTP response."""

    def __init__(self, message: str, status_code: int = 409) -> None:
        super().__init__(message)
        self.status_code = status_code


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def change_set(db: Session, task: Task) -> dict[str, str | None]:
    """Files of the final iteration that differ from the seed (None = deleted)."""
    its = list(db.scalars(select(Iteration).where(Iteration.task_id == task.id)))
    if not its:
        return {}
    last = max(i.iteration_number for i in its)
    base = workspace.iteration_dir(task.id, last)
    final = {
        rel: (base / rel).read_text(encoding="utf-8") for rel in workspace.list_source_files(base)
    }
    seed = workspace.read_seed(task.id)
    out: dict[str, str | None] = {p: t for p, t in final.items() if seed.get(p) != t}
    out.update({p: None for p in seed if p not in final})
    return out


def _secret_findings(files: dict[str, str | None]) -> list[str]:
    bad = []
    for path, text in files.items():
        if text is not None and (kinds := scan_secrets(path, text)):
            bad.append(f"{path}: {', '.join(kinds)}")
    return bad


def save_token(db: Session, org_id: uuid.UUID, token: str) -> None:
    from app.utils.security import encrypt_secret

    row = db.scalars(
        select(OrgIntegration).where(
            OrgIntegration.org_id == org_id, OrgIntegration.provider == "github"
        )
    ).first()
    if row is None:
        db.add(OrgIntegration(org_id=org_id, provider="github", token_enc=encrypt_secret(token)))
    else:
        row.token_enc = encrypt_secret(token)
    db.commit()


def has_token(db: Session, org_id: uuid.UUID) -> bool:
    return _token(db, org_id) is not None


def _token(db: Session, org_id: uuid.UUID) -> str | None:
    row = db.scalars(
        select(OrgIntegration).where(
            OrgIntegration.org_id == org_id, OrgIntegration.provider == "github"
        )
    ).first()
    return decrypt_secret(row.token_enc) if row else None


def request_publish(
    db: Session,
    *,
    task: Task,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    repo: str,
    base_branch: str,
    request: Request | None,
) -> PublishRequest:
    if task.status != "COMPLETED":
        raise PublishError("only a COMPLETED task can be published")
    if not github_service.valid_repo(repo) or not github_service.valid_branch(base_branch):
        raise PublishError("invalid repository or branch name", 422)
    if not has_token(db, org_id):
        raise PublishError("no GitHub token is configured for this organization", 422)
    open_req = db.scalars(
        select(PublishRequest).where(
            PublishRequest.task_id == task.id, PublishRequest.status.in_(("requested", "approved"))
        )
    ).first()
    if open_req is not None:
        raise PublishError("a publish request for this task is already open")
    files = change_set(db, task)
    if not files:
        raise PublishError("the task produced no changes to publish")
    if findings := _secret_findings(files):
        raise PublishError("possible secrets in the change set: " + "; ".join(findings[:5]), 422)
    req = PublishRequest(
        task_id=task.id, org_id=org_id, repo=repo, base_branch=base_branch,
        branch=f"loopforge/task-{str(task.id)[:8]}", requested_by=user_id,
    )  # fmt: skip
    db.add(req)
    db.flush()
    audit_service.record(
        db, org_id=org_id, actor_id=user_id, action="publish.requested", target_type="task",
        target_id=task.id, detail={"publish": str(req.id), "repo": repo, "files": len(files)},
        request=request, commit=False,
    )  # fmt: skip
    db.commit()
    webhook_service.emit_safely(
        db, org_id, "publish.requested", {"task_id": str(task.id), "publish_id": str(req.id)}
    )
    return req


def _locked(db: Session, org_id: uuid.UUID, publish_id: uuid.UUID) -> PublishRequest:
    req = db.scalars(
        select(PublishRequest)
        .where(PublishRequest.id == publish_id, PublishRequest.org_id == org_id)
        .with_for_update()
    ).first()
    if req is None:
        raise PublishError("publish request not found", 404)
    return req


def _members(db: Session, org_id: uuid.UUID) -> int:
    return int(
        db.scalar(select(func.count()).select_from(Membership).where(Membership.org_id == org_id))
        or 0
    )


def reject(
    db: Session, *, org_id: uuid.UUID, user_id: uuid.UUID, publish_id: uuid.UUID,
    request: Request | None,
) -> PublishRequest:  # fmt: skip
    req = _locked(db, org_id, publish_id)
    if req.status != "requested":
        raise PublishError("nothing is waiting for a decision")
    req.status, req.decided_by, req.decided_at = "rejected", user_id, _now()
    audit_service.record(
        db, org_id=org_id, actor_id=user_id, action="publish.rejected", target_type="task",
        target_id=req.task_id, detail={"publish": str(req.id)}, request=request, commit=False,
    )  # fmt: skip
    db.commit()
    webhook_service.emit_safely(
        db, org_id, "publish.rejected", {"task_id": str(req.task_id), "publish_id": str(req.id)}
    )
    return req


def approve_and_push(
    db: Session, *, org_id: uuid.UUID, user_id: uuid.UUID, publish_id: uuid.UUID,
    request: Request | None,
) -> PublishRequest:  # fmt: skip
    req = _locked(db, org_id, publish_id)
    if req.status != "requested":
        raise PublishError("nothing is waiting for a decision")
    if req.requested_by == user_id and _members(db, org_id) > 1:
        raise PublishError("the requester cannot approve their own publish request", 403)
    req.status, req.decided_by, req.decided_at = "approved", user_id, _now()
    audit_service.record(
        db, org_id=org_id, actor_id=user_id, action="publish.approved", target_type="task",
        target_id=req.task_id, detail={"publish": str(req.id), "repo": req.repo}, request=request,
        commit=False,
    )  # fmt: skip
    db.commit()
    webhook_service.emit_safely(
        db, org_id, "publish.approved", {"task_id": str(req.task_id), "publish_id": str(req.id)}
    )
    return push(db, org_id=org_id, publish_id=publish_id, request=request)


def push(
    db: Session, *, org_id: uuid.UUID, publish_id: uuid.UUID, request: Request | None
) -> PublishRequest:
    """The only code path that writes to the provider. Re-reads the approval from the database."""
    req = _locked(db, org_id, publish_id)
    if req.status != "approved" or req.decided_by is None:
        raise PublishError("push refused: no recorded approval")
    task = db.get(Task, req.task_id)
    token = _token(db, org_id)
    if task is None or token is None:
        raise PublishError("task or credentials missing", 422)
    files = change_set(db, task)
    findings = _secret_findings(files)
    try:
        if findings:
            raise GitHubError("possible secrets in the change set")
        report = report_service.build_report(db, task)
        body = report_service.render_markdown(report, report_service.read_readme(db, task.id))
        pr = GitHubClient(token).open_pull_request(
            req.repo,
            base=req.base_branch,
            branch=req.branch,
            files=files,
            title=f"LoopForge: {task.requirement[:60]}",
            body=body,
        )
    except GitHubError as exc:
        req.status, req.error = "failed", str(exc)
        audit_service.record(
            db, org_id=org_id, actor_id=req.decided_by, action="publish.failed",
            target_type="task", target_id=req.task_id,
            detail={"publish": str(req.id), "error": str(exc)}, request=request, commit=False,
        )  # fmt: skip
        db.commit()
        return req
    req.status, req.pr_url, req.head_sha = "pushed", pr.url, pr.head_sha
    audit_service.record(
        db, org_id=org_id, actor_id=req.decided_by, action="publish.pushed", target_type="task",
        target_id=req.task_id, detail={"publish": str(req.id), "pr": pr.url}, request=request,
        commit=False,
    )  # fmt: skip
    db.commit()
    webhook_service.emit_safely(
        db, org_id, "publish.pushed",
        {"task_id": str(req.task_id), "publish_id": str(req.id), "pr_url": pr.url},
    )  # fmt: skip
    return req


def refresh_ci(db: Session, req: PublishRequest) -> PublishRequest:
    """Informational only: CI never changes the task's verdict."""
    if req.status != "pushed" or not req.head_sha:
        return req
    if req.ci_state in ("success", "failure"):
        return req
    token = _token(db, req.org_id)
    if token is None:
        return req
    try:
        req.ci_state = GitHubClient(token).ci_state(req.repo, req.head_sha)
        db.commit()
    except GitHubError:
        db.rollback()
    return req


def list_for_task(db: Session, org_id: uuid.UUID, task_id: uuid.UUID) -> list[PublishRequest]:
    return list(
        db.scalars(
            select(PublishRequest)
            .where(PublishRequest.org_id == org_id, PublishRequest.task_id == task_id)
            .order_by(PublishRequest.created_at)
        )
    )
