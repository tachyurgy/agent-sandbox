"""Seed a deterministic 'world' into the app, then capture it as the baseline.

This is step 1 of Mercor's stated RL-environment method — "create realistic,
data-rich worlds." We build a small but plausible software project (two repos,
a handful of triaged/untriaged issues), then snapshot it as `baseline` so every
episode can `populate()` back to exactly this state.

Run once after the app is up:  python -m sandbox.seed
"""

from __future__ import annotations

from .config import settings
from .gitea_client import GiteaClient, GiteaError
from .state import snapshot

# (repo, description, [(issue_title, issue_body), ...])
WORLD = [
    (
        "acme-web",
        "Customer-facing storefront",
        [
            ("Checkout button does nothing on mobile Safari",
             "Repro: iOS 17, add item, tap Checkout — nothing happens. Console shows a TypeError."),
            ("Add a dark mode toggle",
             "Several customers have asked for a dark theme in the account area."),
            ("Footer shows the wrong copyright year",
             "Footer still reads 2024; should follow the current year."),
        ],
    ),
    (
        "acme-api",
        "Backend REST API",
        [
            ("Rate limiter returns 500 under burst load",
             "Above ~200 rps the limiter throws instead of returning 429. Needs a fix + a regression test."),
        ],
    ),
]


def reset_user_content(client: GiteaClient) -> None:
    """Delete all of the admin's repos so the baseline is clean (keeps the user + token).

    Gitea deletes repos asynchronously, so we poll until they're actually gone —
    otherwise re-creating a same-named repo immediately can 409.
    """
    import time

    for repo in client.list_repos():
        owner, name = repo["full_name"].split("/", 1)
        try:
            client._req("DELETE", f"/api/v1/repos/{owner}/{name}")
        except GiteaError:
            pass
    deadline = time.time() + 10
    while client.list_repos() and time.time() < deadline:
        time.sleep(0.2)


def seed_baseline(client: GiteaClient) -> dict:
    reset_user_content(client)
    created = {"repos": 0, "issues": 0}
    owner = client.whoami()["login"]
    for repo, desc, issues in WORLD:
        client.create_repo(repo, description=desc, auto_init=True)
        created["repos"] += 1
        for title, body in issues:
            client.create_issue(owner, repo, title, body)
            created["issues"] += 1
    return created


def main() -> None:
    client = GiteaClient()
    print("seeding world as", client.whoami()["login"], "...")
    created = seed_baseline(client)
    print("created:", created)
    manifest = snapshot(settings.fixture)  # capture as the baseline
    print("captured baseline snapshot:", manifest)


if __name__ == "__main__":
    main()
