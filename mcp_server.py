"""MCP server exposing two write tools, both approval-gated.

Tools
  append_to_notes(entry, approval_token)         -> appends to out/Product_Pulse_Notes.md
  create_email_draft(subject, body, approval_token) -> writes out/email_drafts/*.eml (never sends)

A tool refuses to run unless `approval_token` was issued by approval.issue_token() for exactly
these arguments (a human clicked/typed "approve"). Tokens are single-use.
Run standalone (stdio): python mcp_server.py
"""
import json
from email.message import EmailMessage
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from approval import consume_token

OUT = Path(__file__).parent / "out"
mcp = FastMCP("pulse-actions")


@mcp.tool()
def append_to_notes(entry: dict, approval_token: str) -> str:
    """Append a pulse entry {date, top_themes, weekly_pulse, identified_fee_issue, explanation_bullets, source_links} to the notes doc."""
    consume_token("append_to_notes", {"entry": entry}, approval_token)
    OUT.mkdir(exist_ok=True)
    notes = OUT / "Product_Pulse_Notes.md"
    if notes.exists() and f"## Entry: {entry['date']}\n" in notes.read_text(encoding="utf-8"):
        return f"Entry {entry['date']} already in {notes}; not appended again"
    block = [f"\n---\n\n## Entry: {entry['date']}\n",
             f"**Top themes:** {', '.join(entry['top_themes'])}\n",
             f"**Identified fee issue:** {entry['identified_fee_issue']}\n",
             "### Weekly pulse\n", entry["weekly_pulse"], "\n### Fee explanation bullets\n"]
    block += [f"- {b}" for b in entry["explanation_bullets"]]
    block += ["\n**Source links:**"] + [f"- {u}" for u in entry["source_links"]]
    block += ["\n<details><summary>raw JSON</summary>\n\n```json\n" + json.dumps(entry, indent=2, ensure_ascii=False) + "\n```\n</details>\n"]
    with notes.open("a", encoding="utf-8") as f:
        f.write("\n".join(block))
    return f"Appended entry {entry['date']} to {notes}"


@mcp.tool()
def create_email_draft(subject: str, body: str, approval_token: str, to: str = "") -> str:
    """Create an email draft (.eml with X-Unsent: 1). Does NOT send."""
    consume_token("create_email_draft", {"subject": subject, "body": body, "to": to}, approval_token)
    drafts = OUT / "email_drafts"
    drafts.mkdir(parents=True, exist_ok=True)
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["To"] = to
    msg["X-Unsent"] = "1"
    msg.set_content(body)
    path = drafts / (subject.split("—")[-1].strip().replace(" ", "_") + ".eml")
    path.write_bytes(bytes(msg))
    path.with_suffix(".txt").write_text(f"Subject: {subject}\n\n{body}\n", encoding="utf-8")
    return f"Draft saved (not sent): {path}"


if __name__ == "__main__":
    mcp.run()
