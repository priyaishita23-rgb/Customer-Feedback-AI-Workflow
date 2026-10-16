"""Review intelligence -> weekly pulse -> fee explainer.

Steps
  1. Review intelligence: embed (all-MiniLM-L6-v2), cluster (KMeans, k<=5), rank themes,
     pull verbatim quotes, detect the most-confused fee/charge.
  2. Weekly product pulse (<=250 words) from those insights.
  3. Fee explainer (<=6 bullets, 2 official links, "Last checked") built ONLY from facts
     retrieved from the official-source corpus in data/sources/official_facts.md (RAG).

No LLM key is required: generation is template-based over retrieved/computed evidence, so every
number in the output traces to a source line or to the review CSV.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.feature_extraction.text import TfidfVectorizer

ROOT = Path(__file__).parent
CSV = ROOT / "data" / "groww_reviews_12w.csv"
FACTS = ROOT / "data" / "sources" / "official_facts.md"
OUT = ROOT / "out"
MODEL = "sentence-transformers/all-MiniLM-L6-v2"
EMB_CACHE = ROOT / "data" / "embeddings.npz"   # saved vectors, so the hosted app needs no torch/model
K = 5
MIN_CHARS = 100          # short reviews ("good app") carry no topic; cluster substantive ones
SOURCES = {
    "S1": "https://groww.in/pricing",
    "S2": "https://groww.in/help/stocks,-f&o,-ipo-&-mtf/discoverable/what-are-the-different-charges-mentioned-in-the-report",
}
HINGLISH = re.compile(r"\b(hai|hain|nhi|nahi|bahut|bhi|ke|ka|ki|ko|mera|mujhe|aap|kya|ho|se|tha|krna|karo|kar|acha|accha|paisa)\b", re.I)
ABUSE = re.compile(r"bloody|fuck|bastard|chor|looter|idiot|stupid|shit|\bf u\b", re.I)

# theme naming lexicon (label -> regex); labels are assigned by lift over the corpus base rate
THEME_LEXICON = {
    "Support, KYC & withdrawal delays": r"support|customer|care|ticket|kyc|withdraw|respon|agent",
    "Brokerage & hidden charges": r"charge|brokerage|fee|deduct|hidden",
    "Charts, orders & update bugs": r"chart|update|lag|crash|button|stop ?loss|scalper|option chain|not working|hang|glitch",
    "Ease of use & overall experience": r"easy|simple|interface|friendly|beginner|smooth|navigate",
}
THEME_ACTIONS = {
    "Support, KYC & withdrawal delays": "Set a 24h SLA on withdrawal/KYC tickets and add status tracking inside the app.",
    "Brokerage & hidden charges": "Show an itemised charge breakdown before and after every sell order.",
    "Charts, orders & update bugs": "Hotfix the post-update chart/scalper overlay regression; add a staged rollout with rollback.",
}

# fee/charge buckets scanned in reviews; `query` is what we retrieve from official sources
FEE_BUCKETS = {
    "Hidden / unexplained charges on sell orders": dict(
        pattern=r"hidden charge|other charges|extra charge|unnecessary charge|additional charge|service charge|too many charges|so many charges",
        query="DP charge on selling shares per sell transaction, sell value under Rs 100, GST and statutory charges deducted"),
    "Brokerage level": dict(pattern=r"brokerage|brokrage|brokerege",
                            query="brokerage charges per order"),
    "DDPI / POA fee": dict(pattern=r"DDPI|\bPOA\b", query="DDPI POA charge"),
    "Statutory taxes (STT / GST / stamp duty)": dict(pattern=r"\bSTT\b|\bGST\b|stamp duty|\btax(?:es)?\b",
                                                      query="STT GST stamp duty statutory charges"),
    "Auto square-off fee": dict(pattern=r"square.?off", query="auto square-off charge"),
    "Account maintenance (AMC)": dict(pattern=r"\bAMC\b|maintenance charge", query="account maintenance charge"),
}
CONFUSION = re.compile(
    r"hidden|unexpected|without (?:any )?(?:notice|notification|informing|inform)|not (?:clear|told|inform)|unclear|"
    r"deduct|cutting|looting|cheat|scam|surprise|not transparent|confus|never (?:told|inform)|clarity|penalt", re.I)

_model = None
_cache: dict[str, np.ndarray] | None = None


def embedder():
    """The sentence-transformers model, loaded only when a text is missing from the embedding cache."""
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer  # heavy (torch); optional when the cache is complete
        _model = SentenceTransformer(MODEL)
    return _model


def _key(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def embed(texts: list[str], batch_size: int = 32) -> np.ndarray:
    """Normalised embeddings for `texts`, served from data/embeddings.npz; encodes and saves any that are missing."""
    global _cache
    if _cache is None:
        _cache = {}
        if EMB_CACHE.exists():
            z = np.load(EMB_CACHE)
            _cache = dict(zip(z["keys"].tolist(), z["vecs"]))
    keys = [_key(t) for t in texts]
    missing = sorted({(k, t) for k, t in zip(keys, texts) if k not in _cache})
    if missing:
        vecs = embedder().encode([t for _, t in missing], batch_size=batch_size, normalize_embeddings=True, show_progress_bar=False)
        _cache.update(zip([k for k, _ in missing], vecs))
        np.savez_compressed(EMB_CACHE, keys=np.array(list(_cache)), vecs=np.stack(list(_cache.values())).astype(np.float32))
    return np.stack([_cache[k] for k in keys])


# ---------------------------------------------------------------- Step 1
def load_reviews(path: Path = CSV) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["text"] = df["text"].fillna("").astype(str)
    df["date"] = pd.to_datetime(df["date"])
    return df


def english_substantive(df: pd.DataFrame) -> pd.DataFrame:
    ascii_share = df["text"].map(lambda s: sum(c.isascii() for c in s) / max(len(s), 1))
    hin = df["text"].map(lambda s: len(HINGLISH.findall(s)))
    return df[(df["text"].str.len() >= MIN_CHARS) & (ascii_share > 0.95) & (hin < 2)].reset_index(drop=True)


def label_clusters(d: pd.DataFrame) -> dict[int, str]:
    """Greedy assignment of lexicon labels by lift (cluster hit-rate / corpus hit-rate)."""
    base = {k: d["text"].str.contains(v, case=False, regex=True).mean() for k, v in THEME_LEXICON.items()}
    lifts = []
    for c in sorted(d["cluster"].unique()):
        sub = d[d["cluster"] == c]["text"]
        for k, v in THEME_LEXICON.items():
            lifts.append((sub.str.contains(v, case=False, regex=True).mean() / max(base[k], 1e-6), c, k))
    labels: dict[int, str] = {}
    for _, c, k in sorted(lifts, reverse=True):
        if c not in labels and k not in labels.values():
            labels[c] = k
    tf = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), min_df=4, max_df=0.3).fit(d["text"])
    names = np.array(tf.get_feature_names_out())
    for c in d["cluster"].unique():
        if c not in labels:
            idx = d.index[d["cluster"] == c]
            top = names[np.asarray(tf.transform(d.loc[idx, "text"]).mean(0)).ravel().argsort()[::-1][:3]]
            labels[c] = "General feedback (" + ", ".join(top) + ")"
    return labels


def pick_quote(sub: pd.DataFrame, centroid: np.ndarray, emb: np.ndarray, prefer: str | None = None) -> dict | None:
    cand = sub[(sub["text"].str.len().between(60, 200)) & (sub["rating"] <= 3) & ~sub["text"].str.contains(ABUSE)]
    if prefer:
        pref = cand[cand["text"].str.contains(prefer, case=False, regex=True)]
        cand = pref if len(pref) else cand
    if cand.empty:
        return None
    score = cand["thumbs_up"].rank(pct=True) * 0.3 + pd.Series(emb[cand.index] @ centroid, index=cand.index).rank(pct=True) * 0.7
    r = cand.loc[score.idxmax()]
    return dict(text=r["text"].replace("\n", " ").strip(), rating=int(r["rating"]), date=str(r["date"].date()), review_id=r["review_id"])


def detect_fee_issue(df: pd.DataFrame) -> dict:
    """Pick the fee bucket with the most <=3-star reviews that mention it AND use confusion language.
    The rating filter drops praise such as "no hidden charges" (5 stars), which also matches "hidden"."""
    rows = []
    for name, spec in FEE_BUCKETS.items():
        m = df["text"].str.contains(spec["pattern"], case=False, regex=True)
        c = m & df["text"].str.contains(CONFUSION) & (df["rating"] <= 3)
        rows.append(dict(fee=name, mentions=int(m.sum()), confusion_mentions=int(c.sum()), query=spec["query"]))
    rows.sort(key=lambda r: (r["confusion_mentions"], r["mentions"]), reverse=True)
    top = rows[0]
    spec = FEE_BUCKETS[top["fee"]]
    m = df["text"].str.contains(spec["pattern"], case=False, regex=True) & df["text"].str.contains(CONFUSION)
    ev = df[m & (df["rating"] <= 3) & df["text"].str.len().between(60, 260) & ~df["text"].str.contains(ABUSE)].sort_values("thumbs_up", ascending=False)
    top["evidence"] = [dict(text=t.replace("\n", " "), date=str(d.date()), rating=int(r)) for t, d, r in
                       zip(ev["text"].head(3), ev["date"].head(3), ev["rating"].head(3))]
    top["all_buckets"] = [{k: v for k, v in r.items() if k != "query"} for r in rows]
    return top


def review_intelligence(asof: dt.date | None = None) -> dict:
    df = load_reviews()
    asof = asof or df["date"].max().date()
    d = english_substantive(df)
    emb = embed(d["text"].tolist(), batch_size=128)
    km = KMeans(K, n_init=20, random_state=42).fit(emb)
    d["cluster"] = km.labels_
    labels = label_clusters(d)

    week_start = pd.Timestamp(asof) - pd.Timedelta(days=6)
    themes = []
    for c, label in labels.items():
        sub = d[d["cluster"] == c]
        neg = sub[sub["rating"] <= 3]
        prior_weeks = max((week_start - df["date"].min()).days / 7, 1)
        themes.append(dict(
            cluster=int(c), label=label, reviews=len(sub), avg_rating=round(float(sub["rating"].mean()), 2),
            negative_reviews=len(neg),
            neg_last_week=int((neg["date"] >= week_start).sum()),
            neg_weekly_avg_before=round(float((neg["date"] < week_start).sum() / prior_weeks), 1),
        ))
    # Rank by issue volume (<=3-star reviews): a product pulse should surface what hurts users most.
    themes.sort(key=lambda t: t["negative_reviews"], reverse=True)
    fee = detect_fee_issue(df)

    quotes = []
    for t in themes[:3]:
        sub = d[d["cluster"] == t["cluster"]]
        prefer = r"(?:sell|sold|deduct|profit).*(?:charge|brokerage)|(?:charge|brokerage).*(?:sell|sold|deduct)" if t["label"] == "Brokerage & hidden charges" else THEME_LEXICON.get(t["label"])
        q = pick_quote(sub, km.cluster_centers_[t["cluster"]], emb, prefer)
        if t["label"] == "Brokerage & hidden charges" and fee["evidence"]:
            q = dict(fee["evidence"][0], review_id="fee-evidence")  # tie the quote to the detected fee issue
        if q:
            quotes.append(dict(theme=t["label"], **q))
    return dict(asof=str(asof), window=[str(df["date"].min().date()), str(df["date"].max().date())],
                total_reviews=len(df), clustered_reviews=len(d), avg_rating_all=round(float(df["rating"].mean()), 2),
                themes=themes, top_themes=[t["label"] for t in themes[:3]], quotes=quotes, fee_issue=fee)


# ---------------------------------------------------------------- Step 2
def words(s: str) -> int:
    return len(re.findall(r"\S+", s))


def weekly_pulse(ins: dict) -> str:
    top = ins["themes"][:3]
    fee = ins["fee_issue"]
    asof = dt.date.fromisoformat(ins["asof"])
    lines = [f"# Weekly Product Pulse: Groww (week ending {asof:%d %b %Y})", "",
             f"**Top themes** ({ins['clustered_reviews']} detailed reviews, {ins['window'][0]} to {ins['window'][1]}):"]
    for i, t in enumerate(top, 1):
        lines.append(f"{i}. **{t['label']}**: {t['negative_reviews']} negative reviews, avg {t['avg_rating']}★")
    lines += ["", "**User voices**"]
    lines += [f"- “{q['text']}” ({q['rating']}★)" for q in ins["quotes"][:3]]
    rising = max(top, key=lambda t: t["neg_last_week"] / max(t["neg_weekly_avg_before"], 1))
    spike = rising["neg_last_week"] >= 1.25 * rising["neg_weekly_avg_before"]
    trend = (f"“{rising['label']}” is trending up ({rising['neg_last_week']} negative this week vs "
             f"{rising['neg_weekly_avg_before']}/week before)." if spike else "No top theme spiked this week.")
    lines += ["", "**Key observation**",
              f"Users call deductions on sell orders “hidden charges”: {fee['confusion_mentions']} reviews pair a charge "
              f"term with confusion language (brokerage-level complaints are mostly about price). The Groww blog still lists "
              f"older DP figures than the pricing page. {trend}",
              "", "**Actions**"]
    acts = [THEME_ACTIONS[t["label"]] for t in top if t["label"] in THEME_ACTIONS]
    acts.append("Align the Groww blog/help DP-charge figures with the pricing page.")
    for i, a in enumerate(acts[:3], 1):
        lines.append(f"{i}. {a}")
    lines += ["", "_Support: see the attached DP-charge explainer._"]
    text = "\n".join(lines)
    assert words(text) <= 250, f"pulse is {words(text)} words"
    return text


# ---------------------------------------------------------------- Step 3 (RAG)
def load_facts() -> tuple[list[dict], str]:
    raw = FACTS.read_text(encoding="utf-8")
    captured = re.search(r"Captured (\d{4}-\d{2}-\d{2})", raw).group(1)
    facts = [dict(src=m.group(1), text=m.group(2).strip()) for m in re.finditer(r"^\[(S\d)\]\s+(.*)$", raw, re.M)]
    return facts, captured


def retrieve(query: str, facts: list[dict], k: int = 8) -> list[dict]:
    F = embed([f["text"] for f in facts])
    q = embed([query])[0]
    sims = F @ q
    return [dict(facts[i], score=round(float(sims[i]), 3)) for i in np.argsort(-sims)[:k]]


def fee_explainer(ins: dict) -> dict:
    fee = ins["fee_issue"]
    facts, captured = load_facts()
    hits = retrieve(fee["query"], facts)
    bullets = [h["text"] for h in hits[:5]]
    # Worked example derived only from retrieved figures (rates parsed from the DP-charge fact)
    dp = next((h["text"] for h in hits if "DP" in h["text"] and "Rs 16.5" in h["text"]), None)
    gst = next((h["text"] for h in hits if "GST of 18%" in h["text"]), None)
    if dp and gst:
        g, d_ = (float(x) for x in re.search(r"Rs ([\d.]+) from Groww plus a depository fee of Rs ([\d.]+)", dp).groups())
        bullets.append(f"Example (calculated from the listed rates, not a quote): a delivery sell incurs a DP charge of "
                       f"(Rs {g} + Rs {d_}) + 18% GST = Rs {(g + d_) * 1.18:.2f} per sell transaction, in addition to brokerage and statutory charges.")
    bullets = bullets[:6]
    text = "\n".join([f"## {fee['fee']}: what gets deducted when you sell", ""] + [f"- {b}" for b in bullets] + [
        "", "Official sources:", f"- {SOURCES['S1']}", f"- {SOURCES['S2']}", "", f"Last checked: {captured}"])
    return dict(title=fee["fee"], bullets=bullets, source_links=list(SOURCES.values()), last_checked=captured,
                retrieved=hits, markdown=text)


def build_payload(ins: dict, pulse: str, exp: dict) -> dict:
    return dict(date=ins["asof"], top_themes=ins["top_themes"], weekly_pulse=pulse,
                identified_fee_issue=ins["fee_issue"]["fee"], explanation_bullets=exp["bullets"],
                source_links=exp["source_links"], last_checked=exp["last_checked"])


def run() -> dict:
    OUT.mkdir(exist_ok=True)
    ins = review_intelligence()
    pulse = weekly_pulse(ins)
    exp = fee_explainer(ins)
    payload = build_payload(ins, pulse, exp)
    (OUT / "insights.json").write_text(json.dumps(ins, indent=2, ensure_ascii=False), encoding="utf-8")
    (OUT / "weekly_pulse.md").write_text(pulse + "\n", encoding="utf-8")
    (OUT / "fee_explainer.md").write_text(exp["markdown"] + "\n", encoding="utf-8")
    (OUT / "payload.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return dict(insights=ins, pulse=pulse, explainer=exp, payload=payload)


if __name__ == "__main__":
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    r = run()
    print(r["pulse"], f"\n\n[{words(r['pulse'])} words]\n")
    print(r["explainer"]["markdown"])
