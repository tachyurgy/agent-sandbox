"""FastMCP server exposing the real Gitea app as MCP tools + resources.

This is one of the two ways an agent drives the sandbox (the other is the
browser agent). Product actions become typed tools; the app's live state is a
resource; and the sandbox lifecycle (populate/snapshot/restore) is exposed so an
episode runner can reset state between rollouts.

    python -m sandbox.mcp_server                    # stdio
    MCP_TRANSPORT=http python -m sandbox.mcp_server  # HTTP on :9100
"""

from __future__ import annotations

from typing import Optional

from fastmcp import FastMCP

from . import state
from .app_process import GiteaApp
from .config import settings
from .gitea_client import GiteaClient

mcp = FastMCP(
    name="gitea-sandbox",
    instructions=(
        "Tools to operate a Gitea instance running in a sandbox. populate() to "
        "reset to the baseline world, the repo/issue tools to act, and "
        "snapshot()/restore() to checkpoint or rewind an episode."
    ),
)

_client: Optional[GiteaClient] = None
_app: Optional[GiteaApp] = None


def client() -> GiteaClient:
    global _client
    if _client is None:
        _client = GiteaClient()
    return _client


def app() -> GiteaApp:
    global _app
    if _app is None:
        _app = GiteaApp()
    return _app


def set_owners(app_obj: Optional[GiteaApp] = None, client_obj: Optional[GiteaClient] = None) -> None:
    """Inject the app/client the tools should use so a caller (e.g. the test
    harness) shares a single process owner instead of spawning a competing one."""
    global _app, _client
    if app_obj is not None:
        _app = app_obj
    if client_obj is not None:
        _client = client_obj


def _owner() -> str:
    return client().whoami()["login"]


# -- repo / issue tools ----------------------------------------------------


@mcp.tool
def create_repo(name: str, description: str = "") -> dict:
    """Create a new repository owned by the sandbox user."""
    r = client().create_repo(name, description)
    return {"full_name": r["full_name"], "private": r["private"]}


@mcp.tool
def list_repos() -> list[dict]:
    """List the sandbox user's repositories."""
    return client().list_repos()


@mcp.tool
def create_issue(repo: str, title: str, body: str = "") -> dict:
    """Open an issue on a repo (owned by the sandbox user)."""
    i = client().create_issue(_owner(), repo, title, body)
    return {"number": i["number"], "title": i["title"], "state": i["state"]}


@mcp.tool
def list_issues(repo: str, state: str = "all") -> list[dict]:
    """List issues on a repo. state ∈ open|closed|all."""
    return client().list_issues(_owner(), repo, state)


@mcp.tool
def comment_issue(repo: str, number: int, body: str) -> dict:
    """Add a comment to an issue."""
    c = client().comment_issue(_owner(), repo, number, body)
    return {"id": c["id"], "body": c["body"]}


@mcp.tool
def close_issue(repo: str, number: int) -> dict:
    """Close an issue."""
    i = client().close_issue(_owner(), repo, number)
    return {"number": i["number"], "state": i["state"]}


# -- sandbox lifecycle tools ----------------------------------------------


@mcp.tool
def populate() -> dict:
    """Reset the app to the deterministic baseline world for a fresh episode."""
    return state.populate(client())


@mcp.tool
def snapshot(name: str) -> dict:
    """Capture the full app state (db + repos) under a name."""
    return state.snapshot(name)


@mcp.tool
def restore(name: str) -> dict:
    """Rewind the app to a previously captured snapshot."""
    return state.restore(app(), name)


# -- resources -------------------------------------------------------------


@mcp.resource("repos://all")
def all_repos() -> list[dict]:
    """Live list of repositories."""
    return client().list_repos()


@mcp.resource("issues://{repo}")
def repo_issues(repo: str) -> list[dict]:
    """Live list of issues for a repo."""
    return client().list_issues(_owner(), repo, "all")


def main() -> None:
    if settings.mcp_transport == "http":
        mcp.run(transport="http", host=settings.mcp_host, port=settings.mcp_port)
    else:
        mcp.run()


if __name__ == "__main__":
    main()
