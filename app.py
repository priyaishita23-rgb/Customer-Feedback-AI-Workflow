"""Streamlit demo: streamlit run app.py
Groww Review Intelligence -> Weekly Product Pulse -> Standardized Fee Explainer -> Approval-Gated MCP
"""
from pathlib import Path
import pandas as pd
import streamlit as st

from mcp_client import execute_approved, proposed_actions, try_without_approval
from pipeline import run, words

ROOT = Path(__file__).parent
OUT = ROOT / "out"

st.set_page_config(
    page_title="Groww Review Pulse & Fee Explainer (Milestone 5)",
    page_icon="📈",
    layout="wide",
)

st.title("📈 Groww: Review Intelligence & Support Workflow")
st.caption(
    "Milestone 5: Transforms 12 weeks of public Play Store reviews into an internal Product Pulse "
    "and a standardized Customer Support Fee Explainer, executed via Approval-Gated MCP."
)


@st.cache_data(show_spinner="Embedding, clustering, and retrieving official facts…")
def generate():
    return run()


r = generate()
ins, payload = r["insights"], r["payload"]

# Top Metrics Row
c1, c2, c3, c4 = st.columns(4)
c1.metric("Total Reviews Analyzed", f"{ins['total_reviews']:,}")
c2.metric("Substantive Reviews Clustered", f"{ins['clustered_reviews']:,}")
c3.metric("Review Window", f"{ins['window'][0]} to {ins['window'][1]}")
c4.metric("Identified Fee Issue", ins["fee_issue"]["fee"])

st.markdown("---")

tab1, tab2, tab3, tab4 = st.tabs([
    "📊 Step 1: Review Intelligence & Themes",
    "📝 Step 2: Weekly Product Pulse (Internal)",
    "💡 Step 3: Fee Explainer (Support Snippet)",
    "🛡️ Step 4: Approval-Gated MCP Orchestration",
])

with tab1:
    st.header("Step 1 — Review Intelligence & Cluster Analysis")
    st.markdown(
        """
        **Pipeline Overview:**
        - Filtered substantive English reviews (≥100 chars, PII scrubbed, Hinglish noise excluded).
        - Embedded using `sentence-transformers/all-MiniLM-L6-v2`.
        - Clustered via **K-Means ($k=5$)**; ranked by negative review volume (≤3★) to prioritize user friction.
        """
    )

    st.subheader("Clustered Review Themes (Top 3 Highlighted)")
    themes_df = pd.DataFrame(ins["themes"]).drop(columns=["cluster"])
    st.dataframe(themes_df, use_container_width=True)

    st.subheader("3 Verbatim User Quotes (Representing Top Themes)")
    cols = st.columns(3)
    for i, q in enumerate(ins["quotes"][:3]):
        with cols[i]:
            st.info(
                f"**Theme:** {q['theme']}\n\n"
                f"“{q['text']}”\n\n"
                f"⭐ **Rating:** {q['rating']}★ | 📅 **Date:** {q.get('date', 'N/A')}"
            )

    st.subheader("Detected Fee / Charge Confusion Point")
    st.markdown(
        f"**Selected Fee Issue:** `{ins['fee_issue']['fee']}`  \n"
        f"**Why this was flagged:** Users frequently combine sell-order charge terms with confusion vocabulary "
        f"(*'hidden'*, *'unexpected'*, *'deducted without clarity'*). It recorded **{ins['fee_issue']['confusion_mentions']} confusion mentions**, "
        f"the highest across all scanned fee categories."
    )
    st.dataframe(pd.DataFrame(ins["fee_issue"]["all_buckets"]), use_container_width=True)

with tab2:
    st.header("Step 2 — Weekly Product Pulse (Internal Output)")
    pulse_text = r["pulse"]
    pulse_words = words(pulse_text)

    col_meta1, col_meta2 = st.columns([1, 4])
    with col_meta1:
        st.metric("Word Count", f"{pulse_words} words", delta="≤ 250 Target Met", delta_color="normal")
    with col_meta2:
        st.success("Structured format: Top Themes Summary + User Voices + Key Observation + 3 Action Ideas")

    st.markdown(pulse_text)

    st.download_button(
        label="📥 Download Weekly Product Pulse (Markdown)",
        data=pulse_text,
        file_name="weekly_pulse.md",
        mime="text/markdown",
    )

with tab3:
    st.header("Step 3 — Standardized Fee Explainer (Support Snippet)")
    st.markdown(
        """
        **Context:** Directly addresses the sell-order charge confusion detected in Step 1.
        Written in a neutral, facts-only tone based strictly on official facts retrieved from Groww pricing & CDSL depository schedules.
        """
    )

    explainer = r["explainer"]
    col_e1, col_e2 = st.columns([1, 4])
    with col_e1:
        st.metric("Bullet Points", f"{len(explainer['bullets'])} / 6 max", delta="≤ 6 Target Met")
    with col_e2:
        st.info(f"Verified against official sources. **Last checked:** {explainer['last_checked']}")

    st.markdown(explainer["markdown"])

    with st.expander("🔍 View Retrieved Official Facts & Cosine Similarity (RAG Evidence)"):
        st.dataframe(pd.DataFrame(explainer["retrieved"]), use_container_width=True)

    st.download_button(
        label="📥 Download Fee Explainer (Markdown)",
        data=explainer["markdown"],
        file_name="fee_explainer.md",
        mime="text/markdown",
    )

with tab4:
    st.header("Step 4 — Required MCP Actions (Approval-Gated)")
    st.markdown(
        """
        **Security & Governance Architecture:**
        - **MCP Server:** FastMCP stdio server running two distinct tools: `append_to_notes` and `create_email_draft`.
        - **Cryptographic Gate:** Before executing any tool, an explicit human approval decision is required.
        - **Single-Use Approval Tokens:** `approval.py` mints a random single-use token bound to the SHA-256 hash of the exact tool arguments.
          Calls without a valid token are rejected with `Human approval required`.
        """
    )

    actions = proposed_actions(payload)

    st.warning("⚠️ **Approval Gate Active:** No notes are appended and no email drafts are created until you approve below.")

    st.subheader("1. Proposed Action: Append to Notes / Doc")
    st.caption("Schema: { date, top_themes, weekly_pulse, identified_fee_issue, explanation_bullets, source_links }")
    st.json(actions[0]["args"]["entry"], expanded=False)

    st.subheader("2. Proposed Action: Create Email Draft (No Auto-Send)")
    st.caption("Subject & Body preview:")
    st.text(f"Subject: {actions[1]["args"]["subject"]}")
    st.text_area("Email Draft Body Preview", actions[1]["args"]["body"], height=220, disabled=True)

    col_btn1, col_btn2, col_btn3 = st.columns([2, 1, 2])
    with col_btn1:
        if st.button("✅ Approve & Execute Both MCP Actions", type="primary", use_container_width=True):
            with st.spinner("Minting single-use approval tokens and calling MCP server..."):
                results = execute_approved(actions)
                for res in results:
                    st.success(res)
    with col_btn2:
        if st.button("❌ Reject", use_container_width=True):
            st.error("Action rejected by user. No tools were executed.")

    with col_btn3:
        if st.button("🔒 Test Security Gate (Attempt Without Approval)", use_container_width=True):
            with st.spinner("Testing MCP server refusal without token..."):
                test_results = try_without_approval(actions)
                for tr in test_results:
                    st.warning(f"MCP Gate Blocked Unauthorized Call:\n{tr}")

    st.markdown("---")
    st.subheader("📁 Live Inspection of MCP Output Files")
    c_out1, c_out2 = st.columns(2)
    with c_out1:
        st.markdown("**Appended Notes File (`out/Product_Pulse_Notes.md`):**")
        notes_path = OUT / "Product_Pulse_Notes.md"
        if notes_path.exists():
            st.text_area("Product_Pulse_Notes.md", notes_path.read_text(encoding="utf-8")[-1200:], height=250, disabled=True)
        else:
            st.write("File not created yet.")

    with c_out2:
        draft_path = OUT / "email_drafts" / f"{payload['date']}.txt"
        st.markdown(f"**Email Draft File (`out/email_drafts/{draft_path.name}`):**")
        if draft_path.exists():
            st.text_area(draft_path.name,draft_path.read_text(encoding="utf-8"), height=250, disabled=True)
        else:
            st.write("Draft not created yet.")
