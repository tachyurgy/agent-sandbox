"""The REST client against a live Gitea."""

from __future__ import annotations


def test_version(fresh):
    assert fresh.version().count(".") >= 1


def test_baseline_world(fresh):
    repos = {r["full_name"].split("/")[1] for r in fresh.list_repos()}
    assert {"acme-web", "acme-api"} <= repos


def test_create_and_close_issue(fresh):
    owner = fresh.whoami()["login"]
    issue = fresh.create_issue(owner, "acme-web", "test issue", "body")
    n = issue["number"]
    assert fresh.get_issue(owner, "acme-web", n)["state"] == "open"
    fresh.close_issue(owner, "acme-web", n)
    assert fresh.get_issue(owner, "acme-web", n)["state"] == "closed"
