"""Test fixtures — these exercise the REAL stack.

A single live Gitea process (its real SQLite state), driven for the whole
session by ONE owner so process-group teardown and on-disk DB swaps are
reliable. Per-test isolation uses a fast API reseed (delete + recreate the
world) rather than a process restart, which keeps the suite quick and avoids
port-rebind races; the on-disk snapshot/restore path is exercised explicitly in
test_state.

The suite needs the app configured and a token available (GITEA_TOKEN or the
token file the start script writes). If Gitea can't be reached it skips rather
than failing spuriously.
"""

from __future__ import annotations

import pytest

from sandbox import mcp_server, seed
from sandbox.app_process import GiteaApp
from sandbox.config import settings
from sandbox.gitea_client import GiteaClient


@pytest.fixture(scope="session")
def app():
    if not settings.binary.exists():
        pytest.skip("gitea binary not fetched — run scripts/start_app.sh")
    a = GiteaApp()
    # Take sole ownership: stop any externally-launched instance, run our own.
    if a.is_up():
        a.stop()
    a.start()
    try:
        GiteaClient().version()
    except Exception as exc:  # noqa: BLE001
        a.stop()
        pytest.skip(f"gitea/token not usable ({exc}) — seed the app first")
    # The MCP tools share this one owner instead of spawning a competitor.
    mcp_server.set_owners(app_obj=a, client_obj=GiteaClient())
    yield a
    a.stop()


@pytest.fixture
def client(app) -> GiteaClient:
    return GiteaClient()


@pytest.fixture
def fresh(app) -> GiteaClient:
    """Reset the world to the deterministic baseline via a fast API reseed."""
    c = GiteaClient()
    seed.seed_baseline(c)
    return c
