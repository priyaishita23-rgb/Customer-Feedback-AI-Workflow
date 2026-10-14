"""Builds the proposed MCP actions and runs them through the stdio MCP server after approval."""
import asyncio
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from approval import issue_token

HERE = Path(__file__).parent


def proposed_actions(payload: dict) -> list[dict]:
    """The exact tool calls that will run if (and only if) the human approves."""
    subject = f"Weekly Product Pulse + Customer Clarification — {payload['date']}"
    snippet = ("Support snippet (reusable):\n\n" + "\n".join(f"- {b}" for b in payload["explanation_bullets"]) +
               "\n\nOfficial sources:\n" + "\n".join(f"- {u}" for u in payload["source_links"]) +
               f"\n\nLast checked: {payload['last_checked']}")
    body = f"{payload['weekly_pulse']}\n\n---\n\n{snippet}"
    entry = {k: payload[k] for k in ("date", "top_themes", "weekly_pulse", "identified_fee_issue",
                                     "explanation_bullets", "source_links")}
    return [dict(tool="append_to_notes", args={"entry": entry}),
            dict(tool="create_email_draft", args={"subject": subject, "body": body, "to": ""})]


async def _run(actions: list[dict]) -> list[str]:
    params = StdioServerParameters(command=sys.executable, args=[str(HERE / "mcp_server.py")], cwd=str(HERE))
    results = []
    async with stdio_client(params) as (r, w), ClientSession(r, w) as session:
        await session.initialize()
        for a in actions:
            res = await session.call_tool(a["tool"], {**a["args"], "approval_token": a["token"]})
            results.append(("ERROR: " if res.isError else "") + "".join(getattr(c, "text", "") for c in res.content))
    return results


def execute_approved(actions: list[dict]) -> list[str]:
    """Mint a token per action (this is the ONLY place tokens are issued) and call the MCP server."""
    for a in actions:
        a["token"] = issue_token(a["tool"], a["args"])
    return asyncio.run(_run(actions))


def try_without_approval(actions: list[dict]) -> list[str]:
    """Demonstrates the gate: calling the tools with a bogus token must fail."""
    for a in actions:
        a["token"] = "not-approved"
    return asyncio.run(_run(actions))
