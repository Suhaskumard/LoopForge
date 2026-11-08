"""`loopforge` command line (Phase 11, ADR-0018): drive the API with a scoped API token.

    python -m app.cli run --repo https://github.com/o/r --requirement "add /health" --wait
    python -m app.cli publish TASK_ID --repo owner/name

Environment: LOOPFORGE_URL (default http://localhost:8000), LOOPFORGE_TOKEN (an `lfk_` API token).
Exit codes: 0 success, 1 the task did not complete, 2 usage/transport error.
"""

import argparse
import os
import sys
import time
from collections.abc import Sequence
from typing import Any

import httpx

TERMINAL = {"COMPLETED", "FAILED", "ESCALATED", "CANCELLED"}


class CliError(Exception):
    pass


class Api:
    def __init__(self, base: str, token: str, client: httpx.Client | None = None) -> None:
        self._c = client or httpx.Client(timeout=30.0)
        self._base = base.rstrip("/") + "/api/v1"
        self._h = {"Authorization": f"Bearer {token}"}

    def call(self, method: str, path: str, json: dict[str, Any] | None = None) -> Any:
        try:
            r = self._c.request(method, self._base + path, headers=self._h, json=json)
        except httpx.HTTPError as exc:
            raise CliError(f"cannot reach the server ({type(exc).__name__})") from None
        if r.status_code >= 400:
            try:
                body = r.json()
                detail = body.get("error", {}).get("message", r.text)
            except ValueError:
                detail = r.text
            raise CliError(f"HTTP {r.status_code}: {detail}")
        return r.json() if r.content else None


def _repo_name(url: str) -> str:
    return url.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git") or "repo"


def run_task(
    api: Api, repo: str, requirement: str, wait: bool, poll: float, timeout: float
) -> tuple[dict[str, Any], int]:
    project = api.call("POST", "/projects", {"name": _repo_name(repo)})
    task = api.call(
        "POST",
        "/tasks",
        {
            "project_id": project["id"],
            "requirement": requirement,
            "source_type": "git",
            "git_url": repo,
        },
    )
    task = api.call("POST", f"/tasks/{task['id']}/start")
    if not wait:
        return task, 0
    deadline = time.monotonic() + timeout
    while task["status"] not in TERMINAL:
        if time.monotonic() > deadline:
            raise CliError(f"timed out waiting for task {task['id']} (status {task['status']})")
        time.sleep(poll)
        task = api.call("GET", f"/tasks/{task['id']}")
    return task, 0 if task["status"] == "COMPLETED" else 1


def main(argv: Sequence[str] | None = None, client: httpx.Client | None = None) -> int:
    parser = argparse.ArgumentParser(prog="loopforge")
    parser.add_argument("--url", default=os.environ.get("LOOPFORGE_URL", "http://localhost:8000"))
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="create a task from a git repo and start it")
    run.add_argument("--repo", required=True, help="https git URL of the starting repository")
    run.add_argument("--requirement", required=True)
    run.add_argument("--wait", action="store_true", help="block until the task is finished")
    run.add_argument("--poll", type=float, default=3.0)
    run.add_argument("--timeout", type=float, default=1800.0)
    pub = sub.add_parser("publish", help="request a pull request for a COMPLETED task")
    pub.add_argument("task_id")
    pub.add_argument("--repo", required=True, help="owner/name on GitHub")
    pub.add_argument("--base", default="main")
    args = parser.parse_args(argv)

    token = os.environ.get("LOOPFORGE_TOKEN", "")
    if not token:
        print("error: set LOOPFORGE_TOKEN to an API token", file=sys.stderr)
        return 2
    api = Api(args.url, token, client)
    try:
        if args.command == "run":
            task, code = run_task(
                api, args.repo, args.requirement, args.wait, args.poll, args.timeout
            )
            print(f"task {task['id']} {task['status']}")
            if args.wait:
                print(f"report: {args.url.rstrip('/')}/api/v1/tasks/{task['id']}/report.md")
            return code
        req = api.call(
            "POST",
            f"/tasks/{args.task_id}/publish",
            {"repo": args.repo, "base_branch": args.base},
        )
        print(f"publish request {req['id']} {req['status']} (waiting for an approver)")
        return 0
    except CliError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
