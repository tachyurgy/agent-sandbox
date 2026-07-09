"""RL-style tasks and their verifiers.

Step 3 of Mercor's method — "author rigorous tasks and verifiers." A task is a
natural-language goal handed to an agent; a verifier is an autograder that reads
the app's real state afterward and returns a reward. The agent can be driven by
the MCP tools or by the browser agent — the verifier doesn't care how the state
got there, only whether the goal was met.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .gitea_client import GiteaClient


@dataclass
class Verdict:
    success: bool
    reward: float
    detail: str


@dataclass
class Task:
    id: str
    goal: str                       # what the agent is told to do
    owner: str
    repo: str
    verify: Callable[[GiteaClient], Verdict]


def _file_bug_verifier(repo: str, needle: str) -> Callable[[GiteaClient], Verdict]:
    def verify(client: GiteaClient) -> Verdict:
        owner = client.whoami()["login"]
        issues = client.list_issues(owner, repo, state="open")
        match = [i for i in issues if needle.lower() in i["title"].lower()]
        if match:
            return Verdict(True, 1.0, f"found open issue #{match[0]['number']} matching {needle!r}")
        return Verdict(False, 0.0, f"no open issue matching {needle!r} in {repo}")
    return verify


def _close_issue_verifier(repo: str, number: int) -> Callable[[GiteaClient], Verdict]:
    def verify(client: GiteaClient) -> Verdict:
        owner = client.whoami()["login"]
        issue = client.get_issue(owner, repo, number)
        if issue["state"] == "closed":
            return Verdict(True, 1.0, f"issue #{number} is closed")
        return Verdict(False, 0.0, f"issue #{number} is still {issue['state']}")
    return verify


def default_tasks(owner: str = "sandbox") -> list[Task]:
    """The task set defined against the baseline world (see seed.py)."""
    return [
        Task(
            id="file-outage-bug",
            goal="A customer reports the storefront is completely down. "
                 "File a new issue on the acme-web repo titled exactly "
                 "'Storefront returns 502 for all users'.",
            owner=owner, repo="acme-web",
            verify=_file_bug_verifier("acme-web", "Storefront returns 502 for all users"),
        ),
        Task(
            id="close-fixed-typo",
            goal="The footer copyright-year typo has been fixed and deployed. "
                 "Close the corresponding issue on acme-web.",
            owner=owner, repo="acme-web",
            # In the baseline, the typo issue is #3.
            verify=_close_issue_verifier("acme-web", 3),
        ),
    ]
