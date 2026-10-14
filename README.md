# Customer-Feedback-AI-Workflow

Building an AI workflow for the Groww RAG ChatBot that was made in the previous milestone project that transforms raw customer feedback into a structured internal update and a ready-to-use customer communication.


Product from Milestone 1: **Groww** (stocks / mutual funds app).
Reviews: 13,100 public Google Play reviews, 13 Jul – 4 Oct 2026 (12 weeks).

## How to run
```bash
pip install -r requirements.txt
python fetch_reviews.py --asof 2026-10-05   # optional: re-scrape (CSV is already in data/)
streamlit run app.py                         # UI demo, approval buttons in last tab
# or
python run.py                                # CLI, y/N approval prompt
python run.py --dry-run                      # generate only, no actions
```
No LLM key is needed. Generation is template-based over retrieved evidence (see "Design notes").

## Where MCP approval happens
- **Gate:** `run.py::ask_approval` (CLI prompt) and the last tab of `app.py` (Approve / Reject buttons).
  Nothing is written before that point; the proposed actions are shown first.
- **Enforcement:** `approval.py` mints a single-use token bound to a hash of the exact arguments, and
  only after approval (`mcp_client.execute_approved`). `mcp_server.py` (a real stdio MCP server, two tools)
  refuses any call without a valid token. Verified: calls with a bogus token return
  "Human approval required".
- **Actions after approval:**
  1. `append_to_notes` -> `out/Product_Pulse_Notes.md` with `{date, top_themes, weekly_pulse, identified_fee_issue, explanation_bullets, source_links}`
  2. `create_email_draft` -> `out/email_drafts/<date>.eml` + `.txt`, subject
     `Weekly Product Pulse + Customer Clarification — <date>`. Never sent (`X-Unsent: 1`).
- Approving the same week twice is safe: `append_to_notes` skips a date already in the notes file.
- Notes/Gmail are local-file stand-ins. To target Google Docs/Gmail, swap the two tool bodies in `mcp_server.py`; the gate is unchanged.

## What fee issue was identified from reviews
**"Hidden" / unexplained charges deducted on sell orders**: the stack of DP charge + GST + statutory
levies on top of brokerage. 28 reviews combine a charge term with confusion language (hidden, deducted, not told…),
the highest of the buckets scanned (brokerage level: 22, mostly "too expensive" rather than "unclear";
DDPI fee: 4; auto square-off: 4). Typical review: "Too many hidden charges…".
Note: the sample fee in the brief (exit load) appears in 1 of 13,100 reviews, so it was not used.
Per-bucket counts: `out/insights.json` -> `fee_issue.all_buckets`.

## Pipeline
1. **Review intelligence** (`pipeline.py`): keep English reviews ≥100 chars (940; shorter ones like "good app" carry no topic),
   embed with `all-MiniLM-L6-v2`, KMeans k=5, label clusters by keyword lift, rank by number of ≤3★ reviews, take top 3,
   pick one verbatim quote per theme.
2. **Weekly pulse** (`out/weekly_pulse.md`, 239 words, asserted ≤250).
3. **Fee explainer** (`out/fee_explainer.md`): retrieves facts from `data/sources/official_facts.md`
   (embedding similarity), ≤6 bullets, 2 official links, "Last checked".

## Design notes / limits
- Sentiment dominates embeddings on short reviews, hence the length filter; two clusters remain broad (ease of use / general).
- Facts were captured by hand-reading official pages on 2026-10-05; "Last checked" is that date. Re-verify before sending.
- The Groww blog still shows older numbers (Rs 15 DP charge, Rs 2 min brokerage) than the pricing page (Rs 16.5, Rs 5); the
  pricing page is treated as authoritative, and the conflict is raised as an action item.
- DP fee example (Rs 23.60) is calculated from listed rates, labelled as such.
- The `.env` LLM keys in the parent folder returned 401, so no LLM was used.
- Reviewer names are dropped from the CSV; emails/phones are masked.

## Deliverables map
| Deliverable | File |
|---|---|
| Weekly product pulse | `out/weekly_pulse.md` |
| Notes/Doc appended entry | `out/Product_Pulse_Notes.md` |
| Email draft | `out/email_drafts/2026-10-04.txt` (+ `.eml`) |
| Reviews CSV sample | `data/reviews_sample.csv` (full: `data/groww_reviews_12w.csv`) |
| Source list | `sources.md` |
| Demo | run `streamlit run app.py` (record ≤3 min) |
