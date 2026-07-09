"""REST client for Gitea — the surface the MCP tools and verifiers use.

Gitea's real HTTP API is what makes it agent-operable without touching its
internals. This client wraps just the endpoints the environment needs.
"""

from __future__ import annotations

from typing import Any, Optional

import httpx

from .config import settings


class GiteaError(RuntimeError):
    def __init__(self, status: int, body: str) -> None:
        super().__init__(f"gitea {status}: {body[:300]}")
        self.status = status
        self.body = body


class GiteaClient:
    def __init__(self, base_url: Optional[str] = None, token: Optional[str] = None) -> None:
        self.base_url = (base_url or settings.base_url).rstrip("/")
        self._token = token or settings.token()

    def _req(self, method: str, path: str, **kw: Any) -> Any:
        headers = kw.pop("headers", {})
        headers["Authorization"] = f"token {self._token}"
        with httpx.Client(base_url=self.base_url, timeout=settings.http_timeout) as c:
            r = c.request(method, path, headers=headers, **kw)
        if r.status_code >= 400:
            raise GiteaError(r.status_code, r.text)
        if r.headers.get("content-type", "").startswith("application/json"):
            return r.json()
        return r.text

    # -- meta ---------------------------------------------------------------

    def version(self) -> str:
        with httpx.Client(base_url=self.base_url, timeout=5) as c:
            return c.get("/api/v1/version").json()["version"]

    def whoami(self) -> dict:
        return self._req("GET", "/api/v1/user")

    # -- repos --------------------------------------------------------------

    def create_repo(self, name: str, description: str = "", private: bool = False,
                    auto_init: bool = True) -> dict:
        return self._req("POST", "/api/v1/user/repos", json={
            "name": name, "description": description,
            "private": private, "auto_init": auto_init,
        })

    def list_repos(self) -> list[dict]:
        data = self._req("GET", "/api/v1/user/repos", params={"limit": 50})
        return [{"full_name": r["full_name"], "description": r.get("description", ""),
                 "private": r["private"]} for r in data]

    # -- issues -------------------------------------------------------------

    def create_issue(self, owner: str, repo: str, title: str, body: str = "",
                     labels: Optional[list[int]] = None) -> dict:
        payload: dict = {"title": title, "body": body}
        if labels:
            payload["labels"] = labels
        return self._req("POST", f"/api/v1/repos/{owner}/{repo}/issues", json=payload)

    def list_issues(self, owner: str, repo: str, state: str = "all") -> list[dict]:
        data = self._req("GET", f"/api/v1/repos/{owner}/{repo}/issues",
                         params={"state": state, "type": "issues", "limit": 50})
        return [{"number": i["number"], "title": i["title"], "state": i["state"],
                 "assignee": (i.get("assignee") or {}).get("login")} for i in data]

    def get_issue(self, owner: str, repo: str, number: int) -> dict:
        return self._req("GET", f"/api/v1/repos/{owner}/{repo}/issues/{number}")

    def comment_issue(self, owner: str, repo: str, number: int, body: str) -> dict:
        return self._req("POST", f"/api/v1/repos/{owner}/{repo}/issues/{number}/comments",
                         json={"body": body})

    def edit_issue(self, owner: str, repo: str, number: int, **fields: Any) -> dict:
        return self._req("PATCH", f"/api/v1/repos/{owner}/{repo}/issues/{number}",
                         json=fields)

    def close_issue(self, owner: str, repo: str, number: int) -> dict:
        return self.edit_issue(owner, repo, number, state="closed")
