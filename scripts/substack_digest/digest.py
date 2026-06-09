#!/usr/bin/env python3
"""
Daily Substack digest: fetches RSS feeds, scores posts by keyword relevance
(health / nutrition / muscle building), and emails a digest via Resend.
No AI API key required.
"""

import os
import sys
import datetime
import re
from email.utils import parsedate_to_datetime

import feedparser
import resend

INTEREST_KEYWORDS = [
    "health", "wellness", "nutrition", "muscle", "protein", "carb",
    "fat loss", "weight loss", "diet", "exercise", "workout", "training",
    "strength", "hypertrophy", "gym", "fitness", "calories", "macros",
    "supplement", "creatine", "sleep", "recovery", "inflammation",
    "gut health", "metabol", "insulin", "hormone", "testosterone",
    "cortisol", "cardio", "running", "lifting", "body composition",
]


def fetch_feed(url: str) -> list[dict]:
    feed = feedparser.parse(url)
    posts = []
    for entry in feed.entries:
        pub_date = None
        for attr in ("published", "updated"):
            if hasattr(entry, attr):
                try:
                    pub_date = parsedate_to_datetime(getattr(entry, attr))
                    break
                except Exception:
                    pass

        summary = ""
        if hasattr(entry, "summary"):
            summary = entry.summary
        elif hasattr(entry, "content") and entry.content:
            summary = entry.content[0].value
        summary = re.sub(r"<[^>]+>", "", summary).strip()[:800]

        posts.append(
            {
                "title": getattr(entry, "title", "(no title)"),
                "url": getattr(entry, "link", ""),
                "author": getattr(entry, "author", feed.feed.get("title", "Unknown")),
                "publication": feed.feed.get("title", "Unknown"),
                "published": pub_date.isoformat() if pub_date else None,
                "published_dt": pub_date,
                "summary": summary,
            }
        )
    return posts


def filter_recent(posts: list[dict], hours: int = 24) -> list[dict]:
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=hours)
    recent = []
    for p in posts:
        dt = p.get("published_dt")
        if dt is None or dt >= cutoff:
            recent.append(p)
    return recent


def score_post(post: dict) -> tuple[int, list[str]]:
    """Return (score 0-10, matched_keywords) based on keyword hits."""
    text = (post["title"] + " " + post["summary"]).lower()
    matched = [kw for kw in INTEREST_KEYWORDS if kw in text]
    # Cap at 10; each unique keyword hit = 1 point
    score = min(len(matched) * 2, 10) if matched else 0
    return score, matched


def filter_by_keywords(posts: list[dict], min_score: int = 2) -> list[dict]:
    results = []
    for post in posts:
        score, matched = score_post(post)
        if score < min_score:
            continue
        results.append(
            {
                "title": post["title"],
                "url": post["url"],
                "publication": post["publication"],
                "author": post["author"],
                "published": post["published"],
                "summary": post["summary"],
                "relevance_score": score,
                "key_topics": matched[:6],
                "relevance_reason": f"Matched keywords: {', '.join(matched[:5])}.",
            }
        )
    results.sort(key=lambda p: p["relevance_score"], reverse=True)
    return results


def build_email(posts: list[dict], today: str) -> tuple[str, str, str]:
    if not posts:
        subject = f"Substack Digest {today} — No new relevant posts"
        plain = "No new posts matching your interests (health, nutrition, muscle building) in the last 24 hours."
        html = f"<p>{plain}</p>"
        return subject, plain, html

    subject = f"Substack Digest {today} — {len(posts)} post{'s' if len(posts) != 1 else ''}"

    lines = [
        f"Your Substack Digest — {today}",
        "Interests: health, wellness, nutrition, muscle building",
        "=" * 60,
        "",
    ]
    for i, post in enumerate(posts, 1):
        lines += [
            f"{i}. {post['title']}",
            f"   Publication: {post['publication']}",
            f"   Author: {post['author']}",
            f"   Relevance: {post['relevance_score']}/10 — {post['relevance_reason']}",
            f"   Topics: {', '.join(post.get('key_topics', []))}",
            f"   Summary: {post['summary']}",
            f"   Read: {post['url']}",
            "",
        ]
    plain = "\n".join(lines)

    html_parts = [
        "<!DOCTYPE html>",
        "<html><body style='font-family: Georgia, serif; max-width: 680px; margin: 0 auto; padding: 20px; color: #222;'>",
        f"<h1 style='font-size: 1.4em; border-bottom: 2px solid #333; padding-bottom: 8px;'>Substack Digest &mdash; {today}</h1>",
        "<p style='color: #666; font-size: 0.9em;'>Curated for: health &middot; wellness &middot; nutrition &middot; muscle building</p>",
    ]
    for post in posts:
        score = post["relevance_score"]
        bar_color = "#2ecc71" if score >= 8 else "#f39c12" if score >= 4 else "#e74c3c"
        topics_html = " ".join(
            f"<span style='background:#f0f0f0; border-radius:3px; padding:2px 6px; font-size:0.8em; margin-right:4px;'>{t}</span>"
            for t in post.get("key_topics", [])
        )
        pub_date = (post.get("published") or "")[:10]
        html_parts.append(
            f"<div style='border-left: 4px solid {bar_color}; padding: 12px 16px; margin: 20px 0; background: #fafafa;'>"
            f"<h2 style='margin: 0 0 4px; font-size: 1.1em;'>"
            f"<a href='{post['url']}' style='color: #1a1a1a; text-decoration: none;'>{post['title']}</a></h2>"
            f"<p style='margin: 0 0 8px; color: #555; font-size: 0.85em;'>{post['publication']} &middot; {post.get('author', '')} &middot; {pub_date}</p>"
            f"<p style='margin: 0 0 8px; font-size: 0.95em;'>{post['summary']}</p>"
            f"<p style='margin: 0 0 8px; color: #666; font-size: 0.85em; font-style: italic;'>{post['relevance_reason']}</p>"
            f"<div style='margin-bottom: 4px;'>{topics_html}</div>"
            f"<p style='margin: 8px 0 0;'>"
            f"<span style='color: {bar_color}; font-weight: bold; font-size: 0.85em;'>Relevance: {score}/10</span>"
            f" &nbsp;&middot;&nbsp; "
            f"<a href='{post['url']}' style='font-size: 0.85em;'>Read on Substack &rarr;</a>"
            f"</p></div>"
        )
    html_parts.append("</body></html>")

    return subject, plain, "\n".join(html_parts)


def send_email(subject: str, plain: str, html: str, to_email: str, from_email: str) -> None:
    resend.api_key = os.environ["RESEND_API_KEY"]
    resend.Emails.send(
        {
            "from": from_email,
            "to": [to_email],
            "subject": subject,
            "text": plain,
            "html": html,
        }
    )


def main() -> int:
    today = datetime.date.today().isoformat()

    feed_urls: list[str] = []

    private_rss = os.environ.get("SUBSTACK_RSS_URL", "").strip()
    if private_rss:
        feed_urls.append(private_rss)

    for pub_url in os.environ.get("SUBSTACK_PUBLICATIONS", "").split(","):
        pub_url = pub_url.strip().rstrip("/")
        if pub_url:
            if not pub_url.endswith("/feed"):
                pub_url += "/feed"
            feed_urls.append(pub_url)

    if not feed_urls:
        print("ERROR: Set SUBSTACK_RSS_URL and/or SUBSTACK_PUBLICATIONS.")
        return 1

    to_email = os.environ.get("DIGEST_EMAIL_TO", "").strip()
    from_email = os.environ.get("DIGEST_EMAIL_FROM", "digest@resend.dev").strip()
    if not to_email:
        print("ERROR: DIGEST_EMAIL_TO not set.")
        return 1

    all_posts: list[dict] = []
    for url in feed_urls:
        print(f"Fetching: {url}", flush=True)
        try:
            posts = fetch_feed(url)
            print(f"  {len(posts)} posts", flush=True)
            all_posts.extend(posts)
        except Exception as exc:
            print(f"  WARNING: failed to fetch feed — {exc}", flush=True)

    recent = filter_recent(all_posts, hours=24)
    print(f"\n{len(recent)} posts from the last 24 h (of {len(all_posts)} total)", flush=True)

    relevant = filter_by_keywords(recent) if recent else []
    print(f"{len(relevant)} relevant post(s) after keyword filtering", flush=True)

    subject, plain, html = build_email(relevant, today)
    print(f"Sending digest to {to_email}...", flush=True)
    send_email(subject, plain, html, to_email, from_email)
    print("Done.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
