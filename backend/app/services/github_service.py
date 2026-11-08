"""Minimal GitHub REST client for opening a pull request (Phase 11, ADR-0018).

Uses the Git Data API (tree -> commit -> ref -> pull request) over HTTPS, so no git binary, working
copy or SSH key is involved and the token never reaches a subprocess. Tests replace `http_client`
with one backed by `httpx.MockTransport`; that is the "mock Git server".
"""

import re
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import settings

REPO_RE = re.compile(r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$")
BRANCH_RE = re.compile(r"^[A-Za-z0-9._/-]{1,100}$")


class GitHubError(Exception):
    """A GitHub call failed (message is safe to show; it never contains the token)."""


@dataclass(frozen=True)
class PullRequest:
    url: str
    head_sha: str


def http_client() -> httpx.Client:
    return httpx.Client(timeout=settings.github_timeout_seconds, follow_redirects=False)


def valid_repo(repo: str) -> bool:
    return bool(REPO_RE.match(repo)) and ".." not in repo


def valid_branch(branch: str) -> bool:
    return bool(BRANCH_RE.match(branch)) and ".." not in branch and not branch.startswith("/")


class GitHubClient:
    def __init__(self, token: str, client: httpx.Client | None = None) -> None:
        self._client = client or http_client()
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _call(
        self, method: str, path: str, json: dict[str, object] | None = None
    ) -> dict[str, object]:
        try:
            resp = self._client.request(
                method,
                settings.github_api_base.rstrip("/") + path,
                headers=self._headers,
                json=json,
            )
        except httpx.HTTPError as exc:
            raise GitHubError(f"GitHub unreachable ({type(exc).__name__})") from None
        if resp.status_code >= 400:
            raise GitHubError(f"GitHub {method} {path.split('?')[0]} -> HTTP {resp.status_code}")
        data = resp.json()
        if not isinstance(data, dict):
            raise GitHubError("unexpected GitHub response")
        return data

    def open_pull_request(
        self,
        repo: str,
        *,
        base: str,
        branch: str,
        files: dict[str, str | None],
        title: str,
        body: str,
    ) -> PullRequest:
        """`files` maps path -> new content, or None to delete the file."""
        base_ref = self._call("GET", f"/repos/{repo}/git/ref/heads/{base}")
        base_sha = str(base_ref["object"]["sha"])  # type: ignore[index]
        base_commit = self._call("GET", f"/repos/{repo}/git/commits/{base_sha}")
        base_tree = str(base_commit["tree"]["sha"])  # type: ignore[index]
        entries: list[dict[str, Any]] = [
            {
                "path": p,
                "mode": "100644",
                "type": "blob",
                **({"content": c} if c is not None else {"sha": None}),
            }
            for p, c in sorted(files.items())
        ]
        tree = self._call(
            "POST", f"/repos/{repo}/git/trees", json={"base_tree": base_tree, "tree": entries}
        )
        commit = self._call(
            "POST",
            f"/repos/{repo}/git/commits",
            json={"message": title, "tree": tree["sha"], "parents": [base_sha]},
        )
        head_sha = str(commit["sha"])
        self._call(
            "POST", f"/repos/{repo}/git/refs", json={"ref": f"refs/heads/{branch}", "sha": head_sha}
        )
        pr = self._call(
            "POST",
            f"/repos/{repo}/pulls",
            json={"title": title, "head": branch, "base": base, "body": body},
        )
        return PullRequest(url=str(pr["html_url"]), head_sha=head_sha)

    def ci_state(self, repo: str, sha: str) -> str:
        """pending | success | failure | none (no checks reported)."""
        data = self._call("GET", f"/repos/{repo}/commits/{sha}/check-runs")
        runs = data.get("check_runs") or []
        if not runs:
            return "none"
        assert isinstance(runs, list)
        if any(r.get("status") != "completed" for r in runs):
            return "pending"
        ok = {"success", "neutral", "skipped"}
        return "success" if all(r.get("conclusion") in ok for r in runs) else "failure"
