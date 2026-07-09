"""Drive the FastMCP server the way an agent would (in-memory client)."""

from __future__ import annotations

import pytest
from fastmcp import Client

from sandbox import mcp_server

pytestmark = pytest.mark.asyncio


async def test_tools_exposed():
    async with Client(mcp_server.mcp) as c:
        names = {t.name for t in await c.list_tools()}
    assert {"create_issue", "list_issues", "close_issue", "populate", "snapshot", "restore"} <= names


async def test_agent_can_triage_via_mcp(app, fresh):
    async with Client(mcp_server.mcp) as c:
        issues = (await c.call_tool("list_issues", {"repo": "acme-web", "state": "open"})).data
        assert len(issues) >= 1
        target = issues[0]["number"]
        closed = (await c.call_tool("close_issue", {"repo": "acme-web", "number": target})).data
        assert closed["state"] == "closed"
        remaining = (await c.call_tool("list_issues", {"repo": "acme-web", "state": "open"})).data
        assert target not in [i["number"] for i in remaining]
