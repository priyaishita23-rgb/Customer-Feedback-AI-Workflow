"""Export pipeline output for the hosted prototype (prototype/index.html).

python prototype/export_data.py  ->  prototype/data.json

Runs the same pipeline as run.py, then re-derives the per-review theme assignment
(same filter, embeddings and KMeans seed as pipeline.review_intelligence) so the page
can show which reviews sit in which theme.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sklearn.cluster import KMeans  # noqa: E402

import pipeline as p  # noqa: E402


def main():
    r = p.run()
    ins, exp = r["insights"], r["explainer"]

    df = p.load_reviews()
    d = p.english_substantive(df)
    emb = p.embedder().encode(d["text"].tolist(), batch_size=128, normalize_embeddings=True, show_progress_bar=False)
    d["cluster"] = KMeans(p.K, n_init=20, random_state=42).fit(emb).labels_
    labels = p.label_clusters(d)
    assert sorted(labels.values()) == sorted(t["label"] for t in ins["themes"]), "cluster labels drifted from insights"
    theme_of = dict(zip(d["review_id"], d["cluster"].map(labels)))

    facts, captured = p.load_facts()
    data = dict(
        product="Groww",
        app_id="com.nextbillion.groww",
        insights=ins,
        pulse=r["pulse"],
        pulse_words=p.words(r["pulse"]),
        explainer={k: v for k, v in exp.items()},
        payload=r["payload"],
        facts=facts,
        facts_captured=captured,
        sources=p.SOURCES,
        fee_buckets={k: v["pattern"] for k, v in p.FEE_BUCKETS.items()},
        confusion_pattern=p.CONFUSION.pattern,
        min_chars=p.MIN_CHARS,
        reviews=[dict(id=rid, d=str(dt.date()), r=int(rt), t=tx, u=int(tu), th=theme_of.get(rid))
                 for rid, dt, rt, tx, tu in zip(df["review_id"], df["date"], df["rating"], df["text"], df["thumbs_up"])],
    )
    out = Path(__file__).parent / "data.json"
    out.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size / 1e6:.1f} MB, {len(data['reviews'])} reviews, {len(theme_of)} clustered)")


if __name__ == "__main__":
    main()
