"""Streamlit host for the Groww Review Pulse prototype: streamlit run app.py

Serves the same page as the claude.ai prototype (prototype/index.html, white + sage with a dark-mode
toggle). The data is produced live by pipeline.py when the app starts, and the Step 4 buttons
(Approve / Reject / try without approval) run here, against the real stdio MCP server
(mcp_server.py) through the approval gate (approval.py).
"""
import datetime as dt
import json
import re
import sys
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "prototype"))

from export_data import build_data  # noqa: E402
from mcp_client import execute_approved, proposed_actions, try_without_approval  # noqa: E402

OUT = ROOT / "out"
BUILD = ROOT / "build" / "pulse_component"
SKELETON = ('<!doctype html><html><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            "<style>body{margin:0}[hidden]{display:none!important}img{max-width:100%}</style>"
            '<script>window.PULSE_HOST = "streamlit";</script></head><body>')

st.set_page_config(page_title="Groww Review Pulse", page_icon="📈", layout="wide")
# Let the page fill the window: hide Streamlit's header/toolbar and padding.
st.markdown("""<style>
header[data-testid="stHeader"], [data-testid="stToolbar"], [data-testid="stDecoration"], footer { display: none !important; }
.block-container, [data-testid="stMainBlockContainer"] { padding: 0 !important; max-width: 100% !important; }
[data-testid="stVerticalBlock"] { gap: 0 !important; }
iframe { display: block; }
</style>""", unsafe_allow_html=True)


@st.cache_resource(show_spinner="Running the review pipeline on 13,100 reviews…")
def build_page() -> dict:
    """Run the pipeline once per server start and write the page + its data for the component."""
    data = build_data()
    BUILD.mkdir(parents=True, exist_ok=True)
    (BUILD / "data.json").write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    page = (ROOT / "prototype" / "index.html").read_text(encoding="utf-8")
    (BUILD / "index.html").write_text(SKELETON + page + "</body></html>", encoding="utf-8")
    return data["payload"]


def read_notes() -> list[dict]:
    """Entries appended by the MCP tool; each carries its raw JSON block."""
    path = OUT / "Product_Pulse_Notes.md"
    if not path.exists():
        return []
    blocks = re.findall(r"```json\n(.*?)\n```", path.read_text(encoding="utf-8"), re.S)
    return sorted((json.loads(b) for b in blocks), key=lambda e: e["date"], reverse=True)


def read_drafts() -> list[dict]:
    drafts = []
    for path in sorted((OUT / "email_drafts").glob("*.txt"), reverse=True):
        head, _, body = path.read_text(encoding="utf-8").partition("\n\n")
        drafts.append(dict(subject=head.removeprefix("Subject: ").strip(), body=body.rstrip("\n"), to=""))
    return drafts


def log(kind: str, msg: str) -> None:
    st.session_state.log.append(dict(kind=kind, msg=msg, at=dt.datetime.now().strftime("%H:%M:%S")))


def handle(action: str, payload: dict) -> None:
    actions = proposed_actions(payload)
    if action == "approve":
        log("info", "Approved by you. Minting one single-use token per action and calling the MCP server.")
        results = execute_approved(actions)
        for r in results:
            log("bad" if r.startswith("ERROR") else "ok", r.replace(str(ROOT) + "\\", "").replace(str(ROOT) + "/", ""))
        st.session_state.gate = "failed" if any(r.startswith("ERROR") for r in results) else "approved"
    elif action == "reject":
        log("bad", "Rejected. No tool was called and nothing was written.")
        st.session_state.gate = "rejected"
    elif action == "bypass":
        log("warn", "Calling both MCP tools directly with a forged token…")
        for r in try_without_approval(actions):
            log("warn" if r.startswith("ERROR") else "bad", ("Blocked: " if r.startswith("ERROR") else "Unexpected: ") + r.removeprefix("ERROR: "))


payload = build_page()
st.session_state.setdefault("log", [])
st.session_state.setdefault("gate", "pending")
st.session_state.setdefault("handled", None)

pulse_page = components.declare_component("groww_review_pulse", path=str(BUILD))
event = pulse_page(state=dict(gate=st.session_state.gate, log=st.session_state.log,
                              notes=read_notes(), drafts=read_drafts()),
                   key="pulse", default=None)

if event and event.get("nonce") != st.session_state.handled:
    st.session_state.handled = event["nonce"]
    handle(event["action"], payload)
    st.rerun()
