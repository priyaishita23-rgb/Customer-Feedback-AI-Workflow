"""Fetch the last N weeks of public Groww Play Store reviews and write a PII-scrubbed CSV.

Usage: python fetch_reviews.py [--weeks 12] [--asof 2026-10-05]
Output: data/groww_reviews_12w.csv (full) and data/reviews_sample.csv (150-row sample)
"""
import argparse
import datetime as dt
import hashlib
import re

import pandas as pd
from google_play_scraper import Sort, reviews

APP_ID = "com.nextbillion.groww"
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE = re.compile(r"(?<!\d)(?:\+?91[\s-]?)?[6-9]\d{9}(?!\d)")


def scrub(text: str) -> str:
    text = EMAIL.sub("[email]", text or "")
    return PHONE.sub("[phone]", text).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--weeks", type=int, default=12)
    ap.add_argument("--asof", default=dt.date.today().isoformat())
    args = ap.parse_args()
    cutoff = dt.datetime.fromisoformat(args.asof) - dt.timedelta(weeks=args.weeks)

    rows, token = [], None
    while True:
        batch, token = reviews(APP_ID, lang="en", country="in", sort=Sort.NEWEST,
                               count=200, continuation_token=token)
        rows += batch
        if not batch or batch[-1]["at"] < cutoff:
            break
    df = pd.DataFrame(rows)
    df = df[df["at"] >= cutoff]
    out = pd.DataFrame({
        # reviewer name/avatar are deliberately dropped; id is a one-way hash
        "review_id": df["reviewId"].map(lambda s: hashlib.sha1(s.encode()).hexdigest()[:10]),
        "date": df["at"].dt.strftime("%Y-%m-%d"),
        "rating": df["score"],
        "text": df["content"].fillna("").map(scrub),
        "thumbs_up": df["thumbsUpCount"],
        "app_version": df["appVersion"],
    }).sort_values("date", ascending=False)
    out.to_csv("data/groww_reviews_12w.csv", index=False, encoding="utf-8")
    long = out[out["text"].str.len() >= 100]
    pd.concat([long.sample(100, random_state=7), out[out["text"].str.len() < 100].sample(50, random_state=7)]
              ).sort_values("date", ascending=False).to_csv("data/reviews_sample.csv", index=False, encoding="utf-8")
    print(len(out), "reviews", out["date"].min(), "->", out["date"].max())


if __name__ == "__main__":
    main()
